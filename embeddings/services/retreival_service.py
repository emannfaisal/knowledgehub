import math
import re
from collections import Counter

from django.db.models import Q
from sentence_transformers import CrossEncoder

from embeddings.models import DocumentChunk

from .vector_store_service import embedding_model, get_vector_store

# Initialize the cross-encoder reranker (cached)
_reranker = None

def _get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    return _reranker


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


def _rerank_chunks(query, chunks):
    """
    Rerank chunks using a cross-encoder model for improved relevance.
    
    Args:
        query: The search query
        chunks: List of chunk dictionaries with 'text' key
        
    Returns:
        List of chunks with updated 'rerank_score' and sorted by relevance
    """
    if not chunks:
        return chunks
    
    try:
        reranker = _get_reranker()
        
        # Prepare query-chunk pairs for reranking
        pairs = [[query, chunk["text"]] for chunk in chunks]
        
        # Get rerank scores
        rerank_scores = reranker.predict(pairs)
        
        # Add rerank scores to chunks
        for chunk, score in zip(chunks, rerank_scores):
            chunk["rerank_score"] = round(float(score), 4)
        
        # Sort by rerank score
        return sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    except Exception as e:
        print(f"Reranking failed, falling back to hybrid scores: {e}")
        # Fall back to hybrid score if reranking fails
        return sorted(chunks, key=lambda x: x["hybrid_score"], reverse=True)


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
    
    # Limit BM25 computation to avoid processing all chunks
    MAX_BM25_DOCS = 50

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

        # Store similarity score from vector store
        # Normalize to 0-1 range
        similarity_score = getattr(doc, '_score', 0.5) or 0.5
        normalized_score = (similarity_score + 1.0) / 2.0 if similarity_score < 1.0 else similarity_score

        merged_chunks[key] = {
            "text": doc.page_content,
            "document_id": document_id,
            "folder_id": metadata.get("folder_id"),
            "chunk_index": chunk_index,
            "semantic_score": normalized_score,
        }

    query_tokens = _tokenize(query)
    keyword_q = Q()
    for token in query_tokens[:5]:
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

    # Compute semantic scores from vector store if available,
    # otherwise use a default score for keyword-only matches
    semantic_raw_scores = {}
    for key, chunk in merged_chunks.items():
        # Use vector store similarity if available, default to 0.0 for keyword-only matches
        semantic_raw_scores[key] = chunk.get("semantic_score", 0.0)

    # Limit BM25 computation to top chunks only
    limited_items = list(merged_chunks.items())[:MAX_BM25_DOCS]
    
    doc_freqs = Counter()
    total_doc_len = 0

    # Cache tokens in chunks to avoid repeated tokenization
    for key, chunk in limited_items:
        if "tokens" not in chunk:
            chunk["tokens"] = _tokenize(chunk["text"])
        doc_tokens = chunk["tokens"]
        total_doc_len += len(doc_tokens)
        for token in set(doc_tokens):
            doc_freqs[token] += 1

    total_docs = len(limited_items)
    avg_doc_len = (total_doc_len / total_docs) if total_docs else 0.0

    keyword_raw_scores = {}
    for key, chunk in limited_items:
        keyword_raw_scores[key] = _bm25_score(
            query_tokens=query_tokens,
            doc_tokens=chunk["tokens"],
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

    # Get more candidates for reranking to give the cross-encoder a better pool
    rerank_k = max(top_k * 4, 10)
    top_candidates = hybrid_scored_chunks[:rerank_k]
    reranked_chunks = _rerank_chunks(query, top_candidates)
    
    # Return only the top_k final results
    return reranked_chunks[:top_k]
        

