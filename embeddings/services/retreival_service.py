import math
import re
from collections import Counter

from django.db.models import Q

from embeddings.models import DocumentChunk

from .vector_store_service import embedding_model, get_vector_store


def _tokenize(text):
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9_]+", text or "") if len(token) > 1]


def _normalize_scores(raw_scores):
    if not raw_scores:
        return {}

    max_score = max(raw_scores.values())
    if max_score <= 0:
        return {key: 0.0 for key in raw_scores}

    return {key: score / max_score for key, score in raw_scores.items()}


def _chunk_key(document_id, chunk_index, text):
    if document_id is not None and chunk_index is not None:
        return f"{document_id}:{chunk_index}"
    return f"text:{hash(text)}"


def _cosine_similarity(vec_a, vec_b):
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _bm25_score(query_tokens, doc_tokens, doc_freqs, total_docs, avg_doc_len):
    if not doc_tokens or not query_tokens:
        return 0.0

    k1 = 1.5
    b = 0.75
    tf = Counter(doc_tokens)
    doc_len = len(doc_tokens)
    score = 0.0

    for token in query_tokens:
        df = doc_freqs.get(token, 0)
        if df == 0:
            continue

        idf = math.log(1 + ((total_docs - df + 0.5) / (df + 0.5)))
        term_freq = tf.get(token, 0)
        if term_freq == 0:
            continue

        denominator = term_freq + k1 * (1 - b + b * (doc_len / max(avg_doc_len, 1.0)))
        score += idf * ((term_freq * (k1 + 1)) / denominator)

    return score


def retrieve_user_context(query, user_id, top_k=3):
    vector_store = get_vector_store()
    candidate_k = max(top_k * 4, 8)

    semantic_docs = vector_store.similarity_search(
        query,
        k=candidate_k,
        filter={"user_id": str(user_id)},
    )

    merged_chunks = {}
    for doc in semantic_docs:
        metadata = doc.metadata or {}
        document_id = metadata.get("document_id")
        chunk_index = metadata.get("chunk_index")
        key = _chunk_key(document_id, chunk_index, doc.page_content)

        merged_chunks[key] = {
            "text": doc.page_content,
            "document_id": document_id,
            "folder_id": metadata.get("folder_id"),
            "chunk_index": chunk_index,
        }

    query_tokens = _tokenize(query)
    keyword_q = Q()
    for token in query_tokens[:8]:
        keyword_q |= Q(content__icontains=token)

    keyword_candidates = []
    if query_tokens:
        keyword_candidates = list(
            DocumentChunk.objects.filter(user_id=user_id)
            .filter(keyword_q)
            .select_related("document")
            .order_by("-created_at")[: candidate_k * 2]
        )

    for chunk in keyword_candidates:
        key = f"{chunk.document_id}:{chunk.chunk_index}"
        if key not in merged_chunks:
            merged_chunks[key] = {
                "text": chunk.content,
                "document_id": str(chunk.document_id),
                "folder_id": str(chunk.document.folder_id),
                "chunk_index": chunk.chunk_index,
            }

    semantic_raw_scores = {}
    if merged_chunks:
        query_vector = embedding_model.embed_query(query)
        keys = list(merged_chunks.keys())
        chunk_texts = [merged_chunks[key]["text"] for key in keys]
        chunk_vectors = embedding_model.embed_documents(chunk_texts)

        for key, chunk_vector in zip(keys, chunk_vectors):
            cosine = _cosine_similarity(query_vector, chunk_vector)
            semantic_raw_scores[key] = (cosine + 1.0) / 2.0

    doc_tokens_map = {}
    doc_freqs = Counter()
    total_doc_len = 0

    for key, chunk in merged_chunks.items():
        doc_tokens = _tokenize(chunk["text"])
        doc_tokens_map[key] = doc_tokens
        total_doc_len += len(doc_tokens)
        for token in set(doc_tokens):
            doc_freqs[token] += 1

    total_docs = len(merged_chunks)
    avg_doc_len = (total_doc_len / total_docs) if total_docs else 0.0

    keyword_raw_scores = {}
    for key, doc_tokens in doc_tokens_map.items():
        keyword_raw_scores[key] = _bm25_score(
            query_tokens=query_tokens,
            doc_tokens=doc_tokens,
            doc_freqs=doc_freqs,
            total_docs=total_docs,
            avg_doc_len=avg_doc_len,
        )

    semantic_scores = _normalize_scores(semantic_raw_scores)
    keyword_scores = _normalize_scores(keyword_raw_scores)

    semantic_weight = 0.65
    keyword_weight = 0.35

    hybrid_scored_chunks = []
    for key, chunk in merged_chunks.items():
        semantic_score = semantic_scores.get(key, 0.0)
        keyword_score = keyword_scores.get(key, 0.0)
        hybrid_score = (semantic_weight * semantic_score) + (keyword_weight * keyword_score)

        hybrid_scored_chunks.append(
            {
                **chunk,
                "semantic_score": round(semantic_score, 4),
                "keyword_score": round(keyword_score, 4),
                "hybrid_score": round(hybrid_score, 4),
            }
        )

    hybrid_scored_chunks.sort(key=lambda item: item["hybrid_score"], reverse=True)

    return hybrid_scored_chunks[:top_k]
        

