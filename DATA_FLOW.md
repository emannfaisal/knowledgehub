# Knowledge Hub Data Flow Architecture

## System Overview
The Knowledge Hub is a RAG (Retrieval-Augmented Generation) system with three main flows:
1. **Document Ingestion** → Chunks & Vector Storage
2. **Query Processing** → Retrieval & Ranking
3. **Chat** → LLM Response Generation

---

## 1. DOCUMENT INGESTION FLOW

### Entry Point: `knowledge/views.py` → Document Upload

```
User uploads document
    ↓
knowledge/views.py::folder_detail() [POST]
    ↓
models.Document created + saved to DB
    ↓
embeddings/services/ingest_service.py::ingest_documents(document)
```

### Step 1: Load Document
**File:** `embeddings/services/ingest_service.py`
**Function:** `load_document(file_path)`

```
File (PDF/DOC/TXT) 
    ↓
PyPDFLoader / TextLoader / Docx2txtLoader
    ↓
LangChain Document objects with page_content
```

### Step 2: Clean & Chunk Text
**Function:** `ingest_documents(document)` (lines 26-58)

```
Raw text from load_document()
    ↓
Text cleaning: regex substitution for malformed PDFs
    ↓
RecursiveCharacterTextSplitter (chunk_size=600, overlap=120)
    ↓
List of LangChain Document chunks with metadata
```

### Step 3: Save to Database
**Function:** `ingest_documents()` (lines 59-70)

```
For each chunk[i]:
    ↓
    DocumentChunk.objects.create(
        user=document.folder.owner,
        document=document,
        chunk_index=i,
        content=chunk.page_content
    )
    ↓
    Save to embeddings.DocumentChunk table in DB
```

### Step 4: Embed & Store in Vector DB
**Function:** `ingest_documents()` (lines 72-82)
**File:** `embeddings/services/vector_store_service.py`

```
For each chunk:
    ↓
    Add metadata to chunk:
        {
            "document_id": str(document.id),
            "chunk_index": i,
            "folder_id": str(document.folder.id),
            "user_id": str(user.id)
        }
    ↓
embeddings/models.py::embedding_model.embed_documents()
    (HuggingFaceEmbeddings with 'sentence-transformers/all-MiniLM-L6-v2')
    ↓
    Vector embeddings computed (384 dimensions)
    ↓
get_vector_store().add_documents(langchain_chunks)
    ↓
    Chroma vector database (persisted in chroma_db/)
```

### Step 5: Mark Complete
**Function:** `ingest_documents()` (lines 84-88)

```
document.is_embedded = True
document.embedded_at = timezone.now()
document.save()

invalidate_vector_store_cache()
    ↓ Clears cached vector store for fresh data
```

---

## 2. QUERY & RETRIEVAL FLOW

### Entry Point: `chat/views.py` → send_message()

```
User sends chat message
    ↓
chat/views.py::send_message(request, session_id) [POST]
    ↓
user_message = "What is X?"
```

### Step 1: Semantic Search
**File:** `embeddings/services/retreival_service.py`
**Function:** `retrieve_user_context(query, user_id, top_k=3)`

```
query = user_message
    ↓
embedding_model.embed_query(query)
    (Same HuggingFace model as ingestion)
    ↓
    Query vector (384 dimensions)
    ↓
get_vector_store().similarity_search(
    query,
    k=candidate_k,  // max(top_k * 4, 8) = max(12, 8) = 12
    filter={"user_id": str(user_id)}
)
    ↓
    Returns 12 most similar chunks from Chroma
    ↓
    semantic_score = normalized_cosine_similarity
```

### Step 2: Keyword Search (Hybrid Approach)
**Function:** `retrieve_user_context()` (lines 145-160)

```
query_tokens = _tokenize(query)
    ↓ Extracts tokens: "what" → ["what"]
    
for token in query_tokens[:5]:  // Limit to top 5 tokens
    keyword_q |= Q(content__icontains=token)
    ↓
    Build OR query
    ↓
DocumentChunk.objects.filter(user_id=user_id).filter(keyword_q)
    ↓
    Database full-text search
    ↓
    Returns keyword matching chunks
```

### Step 3: Merge Results
**Function:** `retrieve_user_context()` (lines 125-158)

```
merged_chunks = {}

From semantic search:
    ↓
    chunk["semantic_score"] = normalized_similarity
    
From keyword search (if not already in merged_chunks):
    ↓
    chunk["semantic_score"] = 0.0  // Default for keyword-only
```

### Step 4: Score Chunks (Hybrid Ranking)
**Function:** `retrieve_user_context()` (lines 189-210)

#### A. Limited BM25 Computation
```
MAX_BM25_DOCS = 50

limited_items = merged_chunks[:MAX_BM25_DOCS]
    ↓ Only process first 50 chunks for efficiency
    
For each chunk in limited_items:
    ↓
    chunk["tokens"] = _tokenize(chunk["text"])
        ↓ Cache tokens to avoid recalculation
    ↓
    Build frequency maps:
        doc_freqs: Counter of token occurrences across all chunks
        total_doc_len: Total tokens in all chunks
        avg_doc_len: Average tokens per chunk
    ↓
    _bm25_score(
        query_tokens,
        doc_tokens,
        doc_freqs,
        total_docs=50,
        avg_doc_len=AVG
    )
    ↓
    keyword_score for each chunk (0-1 normalized)
```

#### B. Normalize Scores
```
semantic_scores = _normalize_scores(semantic_raw_scores)
    ↓ Scale 0-1 range
    
keyword_scores = _normalize_scores(keyword_raw_scores)
    ↓ Scale 0-1 range
```

#### C. Hybrid Scoring
```
semantic_weight = 0.65
keyword_weight = 0.35

For each chunk:
    ↓
    hybrid_score = (0.65 * semantic_score) + (0.35 * keyword_score)
    ↓
    chunk["hybrid_score"] = round(hybrid_score, 4)
```

### Step 5: Initial Ranking
**Function:** `retrieve_user_context()` (line 213)

```
hybrid_scored_chunks.sort(key=lambda x: x["hybrid_score"], reverse=True)
    ↓
    Sorted by hybrid score (highest first)
```

### Step 6: Cross-Encoder Reranking
**Function:** `retrieve_user_context()` (lines 215-219)

```
rerank_k = max(top_k * 4, 10)  // For top_k=3: max(12, 10) = 12

top_candidates = hybrid_scored_chunks[:rerank_k]
    ↓ Take top 12 candidates
    
_rerank_chunks(query, top_candidates)
    ↓
    pairs = [[query, chunk["text"]] for chunk in top_candidates]
    ↓
    reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    ↓
    rerank_scores = reranker.predict(pairs)
        ↓ ML model scores relevance (0-1)
    ↓
    sorted by rerank_score (highest first)
    ↓
    return reranked_chunks[:top_k]  // Return top 3
```

### Final Result
```
context_chunks = [
    {
        "text": "chunk content",
        "document_id": "doc-uuid",
        "chunk_index": 0,
        "folder_id": "folder-uuid",
        "semantic_score": 0.8234,
        "keyword_score": 0.6123,
        "hybrid_score": 0.7534,
        "rerank_score": 0.9123,
        "tokens": ["cached", "tokens"]
    },
    ...  // Top 3 results
]
```

---

## 3. CHAT & LLM RESPONSE FLOW

### Entry Point: `chat/views.py::send_message()`

```
context_chunks = retrieve_user_context(user_message, user_id, top_k=3)
    ↓ Gets top 3 relevant chunks (from Step 2)
```

### Step 1: Get Conversation Memory
**File:** `chat/services/memory_service.py`

```
memory = get_conversation_memory(session_id)
    ↓
    Retrieves previous messages from ChatSession
    ↓
    history = [HumanMessage(...), AIMessage(...), ...]
```

### Step 2: Build System Prompt
**File:** `chat/views.py` (lines 108-120)

```
context_text = "\n\n".join([
    f"Source: {chunk['document_id']}\n{chunk['text']}"
    for chunk in context_chunks
])
    ↓
    Formatted context from top 3 chunks
    
system_prompt = f"""
You are a helpful assistant.
Always prioritize information in the context.
If context doesn't have answer, say "I don't have that info".

Context:
{context_text}
"""
```

### Step 3: Prepare Messages
**File:** `chat/views.py` (lines 125-128)

```
messages = [
    SystemMessage(content=system_prompt),  // System context
    ...history,                             // Previous chat history
    HumanMessage(content=user_message)     // Current user question
]
```

### Step 4: LLM Inference
**File:** `chat/services/llm_service.py`

```
response = llm.invoke(messages)
    ↓
    LLM generates response based on:
        1. System prompt with document context
        2. Previous conversation history
        3. Current user question
    ↓
    response.content = "Answer text"
```

### Step 5: Store in Memory
**File:** `chat/views.py` (lines 133-134)

```
memory.chat_memory.add_message(HumanMessage(content=user_message))
memory.chat_memory.add_message(AIMessage(content=response.content))
    ↓
    Saved to chat session memory for future context
```

### Step 6: Return to User
**File:** `chat/views.py` (lines 136-140)

```
JsonResponse({
    "role": "assistant",
    "content": response.content,
    "sources": context_chunks  // Show which docs were used
})
    ↓
    Sent to frontend for display
```

---

## Database Models

### `embeddings/models.py::DocumentChunk`
- **Primary Key:** UUID
- **Foreign Keys:**
  - `user` → User (Django auth)
  - `document` → Document (knowledge app)
- **Fields:**
  - `chunk_index` → Position in document
  - `content` → Text of chunk
  - `created_at` → Timestamp

### `knowledge/models.py::Document`
- `user` → Owner
- `folder` → Parent folder
- `file` → File path
- `is_embedded` → Flag if processed
- `embedded_at` → Embedding timestamp

### `chat/models.py::ChatSession`
- `user` → Conversation owner
- `created_at` → Session timestamp

---

## Storage Systems

### 1. PostgreSQL / SQLite (Django ORM)
**Purpose:** Metadata & structure
- DocumentChunk records (text + metadata)
- Documents, Folders, Users
- ChatSession history

### 2. Chroma Vector Database
**Purpose:** Semantic search
- Location: `chroma_db/`
- Stores: 384-dimensional embeddings + metadata
- Used for: Fast similarity search

### 3. Cache (Memory)
**Purpose:** Performance
- `_reranker`: Cached CrossEncoder model (loaded once)
- `get_vector_store()`: LRU cached Chroma instance

---

## Performance Optimizations

| Optimization | Location | Benefit |
|---|---|---|
| Token caching | `_tokenize()` → `chunk["tokens"]` | Avoid recalculating tokens |
| Limited BM25 | `MAX_BM25_DOCS = 50` | Skip 100+ chunks if merged count large |
| Limited keyword search | `query_tokens[:5]` | Reduce DB icontains queries |
| Reranking pool | `rerank_k = max(top_k * 4, 10)` | Give CrossEncoder 10+ items to rank |
| Model caching | `@lru_cache` + `_get_reranker()` | Avoid reloading heavy models |

---

## Data Flow Summary

```
UPLOAD              INGEST              STORE
PDF/DOC/TXT  →  [Load, Clean, Chunk]  →  DB + Vector DB
├─ Load
├─ Split (600 chars, 120 overlap)
├─ Embed (HuggingFace)
└─ Save

CHAT QUERY
User Message  →  [Retrieve]  →  [Rank]  →  [LLM]  →  Response
├─ Semantic search (Vector DB)
├─ Keyword search (Database)
├─ Hybrid scoring (0.65 semantic + 0.35 keyword)
├─ Cross-encoder reranking (ML model)
└─ LLM inference with context
```
