# RAG Document Ingestion Pipeline: Optimality Analysis

## Document Metadata

| Field         | Value                                                                             |
| ------------- | --------------------------------------------------------------------------------- |
| Author        | rag-analyst                                                                       |
| Date          | 2026-03-04                                                                        |
| Source System | mingai                                                                            |
| Target System | mingai (multi-tenant SaaS)                                                        |
| Scope         | Full ingestion pipeline: upload -> extract -> chunk -> embed -> index -> retrieve |

---

## 1. Current Ingestion Pipeline

### 1.1 End-to-End Flow

The current mingai ingestion pipeline spans three services:

```
[SharePoint / Manual Upload]
        |
        v
  Sync Worker (sync_processor.py)
    1. Delta query / file download
    2. Text extraction (document_processor.py)
    3. Chunking (document_processor.py)
    4. Embedding generation (embeddings.py)
    5. Azure AI Search indexing
        |
        v
  API Service (kb/ module)
    6. KB discovery & permission filtering (kb_discovery.py)
    7. Hybrid search: vector + BM25 (index_adapter.py)
    8. Context window assembly (context_window.py)
    9. LLM synthesis (search_orchestrator.py)
```

### 1.2 Source Types and Entry Points

| Source Type | Entry Point                       | Trigger            |
| ----------- | --------------------------------- | ------------------ |
| SharePoint  | `sync_processor.py` delta query   | Scheduled / manual |
| Manual      | Upload API -> `sync_processor.py` | User-initiated     |
| MCP         | `mcp_adapter.py` agent invocation | Real-time at query |

Source: `src/backend/api-service/app/modules/kb/schemas.py` defines `KBSourceType` as `sharepoint | manual | mcp`.

### 1.3 Sync Worker Pipeline

The sync worker (`src/sync-worker/app/services/sync_processor.py`) implements the core ingestion loop:

1. **Job Polling**: Redis BLPOP with 1s timeout for efficient queue consumption (`worker.py:234`).
2. **Delta Detection**: SharePoint delta queries identify new, modified, and deleted files. eTag-based deduplication prevents reprocessing unchanged files.
3. **Text Extraction**: Delegates to `DocumentProcessor` for format-specific extraction.
4. **Chunking**: Token-based splitting with overlap.
5. **Embedding**: Batch embedding generation via `EmbeddingsService`.
6. **Indexing**: Writes chunks + embeddings to Azure AI Search.
7. **Checkpoint Recovery**: Crash-resilient via checkpoint persistence. If the worker crashes mid-sync, it resumes from the last checkpoint rather than restarting.
8. **Progress Tracking**: Job history with `MAX_HISTORY_SIZE = 1000` (`worker.py:31`).

### 1.4 Supported File Formats

The document processor (`src/backend/shared/mingai_shared/services/document_processor.py`) handles:

| Format | Library       | Metadata Extracted    |
| ------ | ------------- | --------------------- |
| PDF    | PyMuPDF/fitz  | Page numbers          |
| DOCX   | python-docx   | Section headings      |
| XLSX   | openpyxl      | Sheet names           |
| PPTX   | python-pptx   | Slide numbers         |
| CSV    | csv module    | Row/column positions  |
| TXT    | built-in      | Line numbers          |
| HTML   | BeautifulSoup | Section headings      |
| JSON   | json module   | Key paths             |
| XML    | xml.etree     | Element paths         |
| Email  | email module  | Subject, sender, date |

### 1.5 Vision-Augmented Ingestion

Images embedded in documents are processed through a separate pipeline:

1. **Extraction** (`image_extraction.py`): Pulls images from PDF, PPTX, DOCX with constraints: `MIN_IMAGE_SIZE=100px`, `MAX_IMAGE_SIZE=1024px`. MD5-based deduplication prevents processing identical images.
2. **Description** (`vision_description.py`): Multimodal LLM generates textual descriptions. Images are optimized to 1500px max dimension, JPEG at 85% quality, targeting 500KB. Retry handling: 2 retries, 3 rate-limit retries, 120s max total wait.
3. **Indexing**: Descriptions are included as chunk content alongside the surrounding text context.

Source: `src/backend/shared/mingai_shared/services/image_extraction.py` and `vision_description.py`.

---

## 2. Chunking Strategy Assessment

### 2.1 Current Implementation

The chunking strategy is defined in `document_processor.py:73-74`:

```
DEFAULT_MAX_TOKENS = 1000
OVERLAP_TOKENS     = 100
```

**Algorithm** (lines 150-226):

1. Split text into paragraphs (double newline).
2. For each paragraph, if it fits within `DEFAULT_MAX_TOKENS`, keep as-is.
3. If a paragraph exceeds the limit, split by sentences (period + space).
4. Accumulate sentences until token budget is reached, then start a new chunk.
5. Apply overlap by prepending the tail of the previous chunk to the next.

**Overlap Calculation** (`_get_overlap_text()`, line 667):
The overlap uses an approximate word count: `int(self.OVERLAP_TOKENS * 0.75)` = 75 words. This is a rough heuristic -- 0.75 words per token is reasonable for English but inaccurate for code, URLs, or non-Latin scripts.

### 2.2 Strengths

| Aspect              | Assessment                                                   |
| ------------------- | ------------------------------------------------------------ |
| Semantic boundaries | Paragraph-first splitting preserves topic coherence          |
| Token counting      | Uses tiktoken (cl100k_base) for accurate token counts        |
| Overlap             | 10% overlap (100/1000) helps maintain cross-chunk context    |
| Location metadata   | Page numbers, slide numbers, sheet names preserved per chunk |

### 2.3 Weaknesses

| Issue                      | Impact                                                   | Evidence                                                    |
| -------------------------- | -------------------------------------------------------- | ----------------------------------------------------------- |
| Fixed chunk size           | One size does not fit all document types                 | `DEFAULT_MAX_TOKENS = 1000` hardcoded, no per-format tuning |
| Sentence splitting naive   | Splits on `. ` which breaks on abbreviations, URLs, code | `document_processor.py` paragraph/sentence split logic      |
| No heading-aware chunking  | Chunks can span section boundaries, mixing topics        | No heading detection in chunk boundaries                    |
| No table-aware chunking    | Tables split mid-row, losing relational structure        | Tables treated as plain text                                |
| Overlap word approximation | 0.75 words/token is inaccurate for mixed content         | `_get_overlap_text()` line 667                              |
| No adaptive sizing         | Short factual docs get same treatment as long narratives | Single `DEFAULT_MAX_TOKENS` for all                         |

### 2.4 Comparison to Best-in-Class

| Feature                          | mingai Current       | Best Practice (2026)                                 |
| -------------------------------- | -------------------- | ---------------------------------------------------- |
| Chunk sizing                     | Fixed 1000 tokens    | Adaptive 256-2048 based on content type              |
| Boundary detection               | Paragraph + sentence | Semantic (heading-aware, section-aware)              |
| Overlap strategy                 | Fixed 100 tokens     | Sliding window with semantic overlap detection       |
| Table handling                   | Plain text split     | Table-aware: keep rows intact, structured extraction |
| Code handling                    | Plain text split     | AST-aware: function/class boundaries                 |
| Hierarchical chunking            | None                 | Parent-child chunks (summary + detail)               |
| Late chunking (embed-then-chunk) | None                 | Emerging technique: full-doc embedding then segment  |

### 2.5 Recommendation

For mingai multi-tenant, implement **adaptive semantic chunking**:

1. **Content-type detection**: Identify tables, code blocks, headings, lists as structural elements.
2. **Heading-aware boundaries**: Never split across heading boundaries. Each section becomes a chunk candidate.
3. **Adaptive size**: 256 tokens for factoid content (FAQs, definitions), 512-1024 for narrative, 1024-2048 for technical documentation.
4. **Hierarchical chunks**: Generate a parent summary chunk (section-level) plus child detail chunks. At retrieval time, return the parent for broad context and children for precision.
5. **Table preservation**: Extract tables as structured data, store both raw and serialized forms.

---

## 3. Embedding Model Assessment

### 3.1 Current Dual-Model Architecture

The system uses two separate embedding models, configured in `embeddings.py:80-81` and `openai_client.py:141-147`:

| Purpose           | Model                  | Dimensions | Used In              |
| ----------------- | ---------------------- | ---------- | -------------------- |
| KB search queries | text-embedding-ada-002 | 1536       | Chat query embedding |
| Document chunks   | text-embedding-3-large | 3072       | Ingestion pipeline   |

This is a **critical architectural mismatch**. The query embedding model (ada-002, 1536d) produces vectors in a different space than the document embedding model (embedding-3-large, 3072d). These vectors are **not directly comparable** -- cosine similarity between a 1536d query vector and a 3072d document vector is mathematically undefined without projection.

### 3.2 How It Works Despite the Mismatch

Investigation of the search path reveals the resolution:

- **Uploaded documents** (manual uploads to conversations): Embedded with `text-embedding-3-large` (3072d). Searched via `operations/documents.py` which also uses the doc embedding model for the query, so query and document are in the same space. top_k=10, min_score=0.3.
- **KB index documents** (SharePoint/manual indexes): Embedded during sync with the sync worker's embedding call. The `index_adapter.py` search path uses `HybridSearchService` which generates the query embedding at search time. The search service must use the same model as ingestion for correct results.

The dual-model design appears intentional: uploaded conversation documents use the higher-quality 3072d model, while KB indexes use the cost-effective 1536d model for the larger corpus. However, this creates two problems:

1. **No cross-space search**: A query against uploaded documents cannot simultaneously search KB indexes with a single embedding.
2. **Model drift risk**: If either model is updated independently, existing embeddings become stale.

Source: `src/backend/shared/mingai_shared/services/embeddings.py:80-81`, `src/backend/shared/mingai_shared/services/openai_client.py:141-147`.

### 3.3 Embedding Cache

Redis-based caching is implemented in `embeddings.py:176-195`:

- **Cache key**: `emb:{model}:{hash(text)}` -- correctly includes model name to prevent dimension mismatch.
- **TTL**: 86400 seconds (24 hours) (`embeddings.py:74`).
- **Batch processing**: `max_batch_size=100`, `max_concurrent_batches=5` (`embeddings.py:76-77`).
- **Token truncation**: Max 8000 tokens per text via tiktoken before embedding API call (`embeddings.py:75`).

### 3.4 Comparison to Best-in-Class

| Feature                    | mingai Current                | Best Practice (2026)                                    |
| -------------------------- | ----------------------------- | ------------------------------------------------------- |
| Model                      | ada-002 (KB) + 3-large (docs) | Single model: text-embedding-3-large or Cohere embed-v4 |
| Dimensions                 | 1536 / 3072 split             | Unified 1024-3072 with Matryoshka support               |
| Quantization               | None (full float32)           | int8 or binary quantization for cost                    |
| Cross-lingual support      | English-optimized             | Multilingual embedding model                            |
| Embedding refresh          | Never (no re-embedding)       | Periodic re-embedding on model updates                  |
| Late interaction (ColBERT) | None                          | ColBERT-style multi-vector for precision                |

### 3.5 Recommendation

For mingai:

1. **Unify on a single embedding model**: `text-embedding-3-large` with Matryoshka dimensionality reduction (store 3072d, search at 1024d for speed, 3072d for precision).
2. **Implement embedding versioning**: Track which model version generated each embedding. When models update, flag stale embeddings for background re-processing.
3. **Add quantization**: Binary quantization for first-pass retrieval (32x storage reduction), then rescore with full-precision vectors.

---

## 4. Index Architecture Assessment

### 4.1 Current Azure AI Search Configuration

Each KB index maps to a dedicated Azure AI Search index. The search configuration is managed per-index:

- **Index creation**: During sync, the sync processor creates/updates the Azure AI Search index.
- **Fields**: `chunk_text`, `chunk_vector`, `doc_title`, `chunk_id`, `doc_url`, and metadata fields.
- **Search mode**: Hybrid (vector + BM25 keyword), with `query_type="semantic"` for reranking.

Source: `index_adapter.py:173` uses `search_config.min_relevance_score` for filtering; the research document `04-rag-pipeline.md:113-126` shows the search query structure.

### 4.2 Per-Tenant Index Isolation

The current architecture uses **one Azure AI Search index per KB source** (not per tenant). In a multi-tenant setup:

- **Tenant A** with 3 SharePoint sites = 3 separate indexes.
- **Tenant B** with 2 SharePoint sites + 1 manual KB = 3 separate indexes.
- **Cross-tenant isolation**: Achieved through permission filtering in `kb_discovery.py`, not at the index level.

This means the Azure AI Search indexes themselves are **not tenant-scoped** -- they are source-scoped. Multi-tenancy is enforced at the API layer via `check_user_permission()` (`kb_discovery.py:359-397`).

### 4.3 Search Pipeline

At query time, the retrieval path is (`search_orchestrator.py`, `kb_search.py`, `index_adapter.py`):

1. **Intent detection**: GPT-5 Mini selects relevant indexes from user's permitted set.
2. **Parallel search**: `asyncio.gather()` across all selected KB sources (`chat/operations/kb_search.py`).
3. **Hybrid search**: Vector similarity + BM25 keyword matching + semantic reranking.
4. **Result deduplication**: By document title, keeping highest-scoring chunk per document (`04-rag-pipeline.md:167-188`).
5. **Content truncation**: 2000 chars per chunk for LLM context (`index_adapter.py:295`).
6. **Context window assembly**: Token budget management with 128K model limit, 4096 token response reserve (`context_window.py`).

### 4.4 Search Parameters

| Parameter              | Value      | Source                              |
| ---------------------- | ---------- | ----------------------------------- |
| top_k (KB search)      | 5          | `kb/service.py:431`                 |
| top_k (doc search)     | 10         | `chat/operations/documents.py`      |
| min_score (doc search) | 0.3        | `chat/operations/documents.py`      |
| min_relevance_score    | per-index  | `index_adapter.py:173`              |
| content truncation     | 2000 chars | `index_adapter.py:295`              |
| citation snippet       | 200 chars  | `index_adapter.py:308-354`          |
| model token limit      | 128,000    | `context_window.py` (GPT-4o family) |
| response reserve       | 4,096      | `context_window.py`                 |

### 4.5 Weaknesses

| Issue                      | Impact                                                              |
| -------------------------- | ------------------------------------------------------------------- |
| No cross-index search      | Cannot search across multiple KBs in a single query to Azure Search |
| Index proliferation        | N tenants x M sources = N\*M indexes, scaling concern               |
| No index partitioning      | Large indexes have no sharding strategy                             |
| top_k=5 is low             | Misses relevant chunks for complex queries                          |
| Title-based dedup is naive | Same content from different titles not deduplicated                 |
| 2000 char truncation       | Loses context for long-form content chunks                          |
| No query expansion         | Relies on glossary rewriting only, no synonym expansion             |

### 4.6 Recommendation

For mingai multi-tenant:

1. **Tenant-scoped indexes**: One index per tenant with a `source_id` filter field, rather than one index per source. This reduces index count from O(tenants \* sources) to O(tenants).
2. **Increase top_k**: Use top_k=10-20 with reranking, then select top 5 after cross-encoder reranking.
3. **Semantic deduplication**: Use embedding similarity for dedup (>0.95 cosine = duplicate), not title matching.
4. **Two-stage retrieval**: First-pass with binary quantized vectors (fast, broad recall), second-pass with full vectors + cross-encoder reranking (precise).

---

## 5. Retrieval Quality Assessment

### 5.1 Query Processing

The query path includes glossary-based rewriting (`kb_search.py:23-77`):

```
User query: "What is our AWS policy?"
Glossary lookup: AWS -> Annual Wage Supplement
Rewritten: "What is our Annual Wage Supplement (AWS) policy?"
```

This is effective for domain-specific acronyms but limited:

- Only handles exact term matches with word boundaries.
- No synonym expansion beyond the glossary.
- No query decomposition for multi-part questions.
- No hypothetical document expansion (HyDE).

### 5.2 Retrieval Path Priority

The `search_orchestrator.py` implements a priority-based routing:

```
1. Document search (uploaded files in conversation)
2. KB search (SharePoint/Manual indexes)
3. Pure LLM (no external sources)
4. Internet search (Perplexity MCP fallback)
```

This is sequential-priority: if documents are found, KB search may still run but document results take precedence. Internet search is a fallback when KB results have low confidence.

### 5.3 Confidence Scoring

Per `04-rag-pipeline.md:329-384`, confidence is a weighted composite:

| Component         | Weight | Calculation                                   |
| ----------------- | ------ | --------------------------------------------- |
| Source agreement  | 0.30   | Variance of vector scores across sources      |
| Vector similarity | 0.30   | Mean of top-3 vector scores                   |
| Coverage          | 0.20   | Key phrase overlap between query and response |
| Text indicators   | 0.20   | Confidence vs uncertainty keyword counting    |

**Weaknesses**:

- Keyword-based confidence indicators ("might be", "possibly") are brittle.
- No user feedback loop to calibrate confidence thresholds.
- Coverage metric uses simple string matching, not semantic similarity.

### 5.4 Context Window Management

`context_window.py` manages the token budget:

- **Total budget**: 128K tokens (GPT-4o family).
- **Response reserve**: 4,096 tokens.
- **System prompt**: Variable (typically 2K-4K tokens).
- **Available for sources**: ~120K tokens.
- **Truncation**: At sentence boundaries, minimum 100 useful tokens per source.

This is well-implemented. The sentence-boundary truncation prevents mid-thought cuts, and the minimum threshold prevents useless fragments.

### 5.5 Comparison to Best-in-Class

| Feature                     | mingai Current                 | Best Practice (2026)                         |
| --------------------------- | ------------------------------ | -------------------------------------------- |
| Query expansion             | Glossary rewriting only        | HyDE + query decomposition + synonyms        |
| Retrieval stages            | Single-pass hybrid search      | Two-stage: broad recall + precise rerank     |
| Reranking                   | Azure semantic reranking       | Cross-encoder reranking (e.g., BGE-reranker) |
| Result fusion               | Title-based dedup + score sort | Reciprocal Rank Fusion (RRF) across signals  |
| Confidence calibration      | Static weights, no learning    | Calibrated with user feedback history        |
| Answer grounding validation | None                           | NLI-based citation verification              |
| Multi-hop reasoning         | None                           | Iterative retrieval for complex queries      |

---

## 6. Multi-Tenant Implications

### 6.1 Current Isolation Model

The current mingai system achieves multi-user isolation through:

1. **Permission Service**: `kb_discovery.py:359-397` checks `check_user_permission()` before any KB access. This consults the `PermissionService` to verify the user's `kb_permissions` / `index_permissions`.
2. **KB Filtering**: `kb_discovery.py:62-63` filters indexes by `permitted_kb_ids` set.
3. **Cache Scoping**: `cache.py` uses per-user cache keys with 1h TTL (`REDIS_CACHE_TTL = 3600`).

This is **user-level** isolation, not **tenant-level**. There is no concept of a "tenant" in the current schema -- users are individually permissioned to specific KBs.

### 6.2 Gaps for True Multi-Tenancy

| Gap                             | Risk                                                 | Severity |
| ------------------------------- | ---------------------------------------------------- | -------- |
| No tenant ID in data model      | Cannot enforce tenant boundary at data layer         | Critical |
| Shared Azure Search indexes     | Cross-tenant data leakage via index misconfiguration | Critical |
| No tenant-scoped encryption     | All tenants share encryption keys                    | High     |
| No tenant-level rate limiting   | One tenant can consume all resources                 | High     |
| No tenant-level embedding cache | Cache pollution across tenants                       | Medium   |
| No tenant-scoped MCP access     | MCP tool results not tenant-filtered                 | High     |
| No data residency controls      | Cannot guarantee data stays in tenant's region       | Medium   |

### 6.3 MCP Multi-Tenancy

The 9 MCP servers (`06-mcp-servers.md`) present additional multi-tenancy challenges:

- **Bloomberg/CapIQ**: Financial data is not tenant-specific but access must be licensed per tenant.
- **Oracle Fusion**: ERP data is inherently tenant-specific; the `customer_id` parameter must be tenant-scoped.
- **Azure AD**: User lookups must be scoped to the tenant's Azure AD directory.
- **Perplexity**: Web search is tenant-neutral but query history must be isolated.

The `mcp_adapter.py` handles OBO (On-Behalf-Of) authentication, which provides user-level scoping. For true multi-tenancy, this needs to be extended to tenant-level credential isolation.

### 6.4 Recommendation

For mingai, implement **tenant-level data isolation**:

1. **Tenant ID propagation**: Add `tenant_id` to every data model, cache key, and API context.
2. **Tenant-scoped indexes**: One Azure AI Search index per tenant (not per source).
3. **Tenant encryption**: Per-tenant encryption keys for data at rest.
4. **Tenant rate limiting**: Resource quotas enforced at the ingestion and query layers.
5. **Tenant-scoped MCP credentials**: Store MCP API keys per tenant, not globally.

---

## 7. Gap Analysis vs Best-in-Class

### 7.1 Overall Maturity Assessment

| Pipeline Stage    | Current Maturity | Target Maturity | Gap      |
| ----------------- | ---------------- | --------------- | -------- |
| Text Extraction   | Good (8/10)      | Excellent       | Small    |
| Chunking          | Adequate (5/10)  | Excellent       | Large    |
| Embedding         | Adequate (6/10)  | Excellent       | Medium   |
| Indexing          | Good (7/10)      | Excellent       | Medium   |
| Retrieval         | Good (7/10)      | Excellent       | Medium   |
| Multi-Tenancy     | Poor (3/10)      | Excellent       | Critical |
| Observability     | Adequate (5/10)  | Excellent       | Large    |
| Vision Processing | Good (7/10)      | Excellent       | Small    |

### 7.2 Critical Gaps

#### Gap 1: No Semantic Chunking

**Current**: Fixed 1000-token chunks with paragraph/sentence splitting.
**Target**: Content-aware chunking that respects document structure (headings, tables, code blocks).
**Impact**: Retrieval precision suffers when chunks span topic boundaries.
**Effort**: Medium (2-3 weeks).

#### Gap 2: Dual Embedding Model Complexity

**Current**: Two separate models (ada-002 + embedding-3-large) for different use cases.
**Target**: Single unified model with Matryoshka support for flexible dimensionality.
**Impact**: Operational complexity, no cross-corpus search, model drift risk.
**Effort**: Medium (1-2 weeks for migration, plus re-embedding time).

#### Gap 3: No Tenant Isolation at Data Layer

**Current**: User-level permission filtering at API layer.
**Target**: Tenant-scoped data isolation with per-tenant indexes and encryption.
**Impact**: Cannot safely serve multiple organizations from one deployment.
**Effort**: Large (4-6 weeks).

#### Gap 4: No Two-Stage Retrieval

**Current**: Single-pass hybrid search with Azure semantic reranking.
**Target**: Broad first-pass retrieval + cross-encoder reranking for top candidates.
**Impact**: Retrieval precision limited, especially for nuanced queries.
**Effort**: Medium (2-3 weeks).

#### Gap 5: No Query Decomposition

**Current**: Single query with glossary rewriting.
**Target**: Multi-step query processing: decomposition, expansion, HyDE generation.
**Impact**: Complex multi-part questions get partial answers.
**Effort**: Medium (1-2 weeks).

#### Gap 6: No Citation Verification

**Current**: LLM generates citations from provided sources, no verification.
**Target**: NLI-based (Natural Language Inference) verification that cited passages support claims.
**Impact**: Hallucinated citations reduce trust.
**Effort**: Medium (2-3 weeks).

#### Gap 7: No Embedding Versioning

**Current**: No tracking of which model version produced embeddings.
**Target**: Versioned embeddings with background re-indexing on model updates.
**Impact**: Model updates silently degrade search quality for existing documents.
**Effort**: Small (1 week).

### 7.3 Non-Critical Gaps (Future Enhancements)

| Gap                               | Priority | Effort |
| --------------------------------- | -------- | ------ |
| Late chunking (embed-then-chunk)  | Low      | Medium |
| ColBERT multi-vector retrieval    | Low      | Large  |
| Graph-based knowledge indexing    | Low      | Large  |
| Agentic RAG (iterative retrieval) | Medium   | Medium |
| Multimodal search (image query)   | Low      | Medium |

---

## 8. Recommended Ingestion Pipeline for mingai

### 8.1 Architecture Overview

```
[Tenant Admin: Connect Source]
         |
         v
  Source Connector (per tenant)
    - SharePoint Graph API
    - Manual Upload API
    - S3/GCS connector (new)
    - Database connector (new)
         |
         v
  Ingestion Worker (tenant-scoped)
    1. Content extraction (enhanced document_processor)
    2. Structure detection (headings, tables, code, lists)
    3. Adaptive semantic chunking
    4. Hierarchical chunk generation (parent + children)
    5. Unified embedding (text-embedding-3-large, 3072d)
    6. Embedding versioning & storage
    7. Tenant-scoped Azure AI Search indexing
         |
         v
  Retrieval Service (tenant-scoped)
    8. Query processing (decompose, expand, HyDE)
    9. Two-stage retrieval (broad recall + rerank)
    10. Cross-encoder reranking
    11. Context window assembly
    12. Citation verification (NLI)
    13. LLM synthesis with grounded response
```

### 8.2 Before/After Comparison

| Component                | mingai (Before)                         | mingai (After)                              |
| ------------------------ | --------------------------------------- | ------------------------------------------- |
| **Chunking**             | Fixed 1000 tokens, paragraph/sentence   | Adaptive 256-2048, heading/table-aware      |
| **Chunk hierarchy**      | Flat chunks only                        | Parent (section summary) + child (detail)   |
| **Embedding model**      | Dual: ada-002 (1536d) + 3-large (3072d) | Single: 3-large (3072d) with Matryoshka     |
| **Embedding versioning** | None                                    | Version tag per chunk, background re-embed  |
| **Index scope**          | Per-source index                        | Per-tenant index with source_id filter      |
| **Search stages**        | Single-pass hybrid                      | Two-stage: broad ANN + cross-encoder rerank |
| **Query processing**     | Glossary rewrite only                   | Decompose + expand + HyDE + glossary        |
| **Deduplication**        | Title-based                             | Semantic similarity (>0.95 cosine)          |
| **Confidence scoring**   | Static weighted formula                 | Calibrated with user feedback, NLI-verified |
| **Tenant isolation**     | User-level permission filter            | Tenant-scoped index + encryption + quotas   |
| **MCP credentials**      | Global shared                           | Per-tenant credential vault                 |
| **Embedding cache**      | User-scoped Redis (24h)                 | Tenant-scoped Redis (24h) + model version   |
| **top_k retrieval**      | 5 (KB), 10 (docs)                       | 20 (first pass) -> 5 (after reranking)      |
| **Content truncation**   | 2000 chars per chunk                    | Dynamic based on token budget allocation    |
| **Image processing**     | Extract + LLM describe                  | Extract + LLM describe + OCR fallback       |

### 8.3 Chunking Strategy (Detailed)

```python
# Recommended chunking configuration per content type
CHUNKING_CONFIG = {
    "narrative": {
        "max_tokens": 1024,
        "overlap_tokens": 128,
        "boundary": "heading_or_paragraph",
    },
    "factoid": {
        "max_tokens": 256,
        "overlap_tokens": 32,
        "boundary": "paragraph",
    },
    "table": {
        "max_tokens": 512,
        "overlap_tokens": 0,  # Tables should not overlap
        "boundary": "row_group",
        "preserve_headers": True,
    },
    "code": {
        "max_tokens": 1024,
        "overlap_tokens": 64,
        "boundary": "function_or_class",
    },
    "slide": {
        "max_tokens": 512,
        "overlap_tokens": 0,
        "boundary": "slide",
    },
}
```

### 8.4 Embedding Strategy (Detailed)

```
Model: text-embedding-3-large
Full dimensions: 3072
Search dimensions: 1024 (Matryoshka truncation for first-pass)
Rerank dimensions: 3072 (full precision for second-pass)

Storage:
- Azure AI Search: 1024d binary quantized (fast ANN)
- Cosmos DB: 3072d full precision (reranking & versioning)

Versioning:
- Each chunk stores: {embedding_model: "3-large", embedding_version: "2026-02", dimensions: 3072}
- Background worker: monitors model updates, queues re-embedding jobs
- Tenant can force re-embed via admin API
```

### 8.5 Two-Stage Retrieval (Detailed)

```
Stage 1 - Broad Recall:
  - Binary quantized vectors (32x smaller)
  - top_k = 50
  - Fast ANN search (<50ms)
  - Hybrid: vector + BM25 keyword

Stage 2 - Precise Reranking:
  - Full-precision vectors
  - Cross-encoder reranker (e.g., BGE-reranker-v2)
  - Rescore top 50 -> select top 5
  - ~200ms additional latency

Total retrieval budget: <500ms (vs current <1s)
```

### 8.6 Tenant Isolation Architecture

```
Per-Tenant Resources:
  - Azure AI Search index: "mingai-{tenant_id}"
  - Redis cache namespace: "tenant:{tenant_id}:*"
  - Encryption key: Azure Key Vault per-tenant key
  - MCP credentials: per-tenant credential store
  - Rate limits: configurable per tenant tier

Index Schema:
  - tenant_id (partition key, not searchable)
  - source_id (filterable)
  - chunk_id (unique key)
  - chunk_text (searchable, full-text)
  - chunk_vector (vector field, 3072d stored as 1024d binary)
  - doc_title, doc_url, page_number (metadata)
  - embedding_model, embedding_version (versioning)
  - created_at, updated_at (timestamps)
  - access_tags (optional: sub-tenant access control)
```

### 8.7 Migration Path

| Phase   | Scope                                    | Duration | Risk   |
| ------- | ---------------------------------------- | -------- | ------ |
| Phase 1 | Tenant-scoped indexes + ID propagation   | 3 weeks  | Medium |
| Phase 2 | Unified embedding model + versioning     | 2 weeks  | Low    |
| Phase 3 | Adaptive semantic chunking               | 3 weeks  | Medium |
| Phase 4 | Two-stage retrieval + cross-encoder      | 2 weeks  | Low    |
| Phase 5 | Query decomposition + HyDE               | 2 weeks  | Low    |
| Phase 6 | Citation verification (NLI)              | 2 weeks  | Low    |
| Phase 7 | Per-tenant encryption + credential vault | 3 weeks  | High   |

**Total estimated duration**: 17 weeks (parallel execution can reduce to ~10 weeks).

### 8.8 Key Metrics to Track

| Metric                        | Current Baseline | Target        |
| ----------------------------- | ---------------- | ------------- |
| Retrieval latency (p50)       | ~800ms           | <300ms        |
| Retrieval latency (p99)       | ~2500ms          | <1000ms       |
| Answer relevance (human eval) | Not measured     | >0.85         |
| Citation accuracy             | Not measured     | >0.95         |
| Chunk utilization (% useful)  | Not measured     | >0.80         |
| Cross-tenant data leakage     | Not measured     | 0 (zero)      |
| Embedding freshness           | No tracking      | <7 days stale |
| Ingestion throughput          | ~100 docs/min    | >500 docs/min |

---

## Appendix A: Source File Reference

| File Path                                                                 | Purpose                                | Key Lines                                                   |
| ------------------------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------- |
| `aihub2/src/backend/shared/aihub_shared/services/document_processor.py`   | Text extraction & chunking             | 73-74 (constants), 150-226 (chunk algorithm), 667 (overlap) |
| `aihub2/src/backend/shared/aihub_shared/services/embeddings.py`           | Embedding generation & caching         | 74-81 (config), 176-195 (cache logic)                       |
| `aihub2/src/backend/shared/aihub_shared/services/openai_client.py`        | Azure OpenAI client config             | 27-38 (connection pool), 141-147 (model deployments)        |
| `aihub2/src/backend/shared/aihub_shared/services/vision_description.py`   | Image description via multimodal LLM   | Image optimization, retry handling                          |
| `aihub2/src/backend/shared/aihub_shared/services/image_extraction.py`     | Image extraction from documents        | MIN/MAX size, MD5 dedup                                     |
| `aihub2/src/sync-worker/app/services/sync_processor.py`                   | Full sync pipeline                     | Delta queries, checkpoint recovery                          |
| `aihub2/src/sync-worker/app/worker.py`                                    | Worker loop                            | 31 (history size), 234 (BLPOP)                              |
| `aihub2/src/backend/api-service/app/modules/kb/service.py`                | Unified KB service                     | 423-550 (search), 431 (top_k)                               |
| `aihub2/src/backend/api-service/app/modules/kb/kb_discovery.py`           | KB enumeration & permissions           | 62-63 (filter), 359-397 (permission check)                  |
| `aihub2/src/backend/api-service/app/modules/kb/kb_search.py`              | Glossary rewriting & search delegation | 23-77 (rewrite), 80-145 (index search)                      |
| `aihub2/src/backend/api-service/app/modules/kb/adapters/index_adapter.py` | Azure AI Search adapter                | 173 (min score), 295 (truncation), 308-354 (citations)      |
| `aihub2/src/backend/api-service/app/modules/kb/adapters/mcp_adapter.py`   | MCP agent adapter                      | OBO auth, tool invocation                                   |
| `aihub2/src/backend/api-service/app/modules/kb/cache.py`                  | KB source caching                      | REDIS_CACHE_TTL = 3600                                      |
| `aihub2/src/backend/api-service/app/modules/chat/operations/kb_search.py` | Parallel KB search                     | asyncio.gather, SSE streaming                               |
| `aihub2/src/backend/api-service/app/modules/chat/operations/documents.py` | Document search                        | top_k=10, min_score=0.3                                     |
| `aihub2/src/backend/api-service/app/modules/chat/search_orchestrator.py`  | Search priority routing                | Document > KB > LLM > Internet                              |
| `aihub2/src/backend/api-service/app/modules/chat/context_window.py`       | Token budget management                | 128K limit, 4096 reserve                                    |
| `aihub2/src/backend/api-service/app/modules/kb/router.py`                 | KB API endpoints                       | Feature flag, permission checks                             |
| `aihub2/src/backend/api-service/app/modules/kb/schemas.py`                | KB data models                         | KBSourceType, KnowledgeBaseConfig                           |

## Appendix B: Research Documents Referenced

| Document               | Path                                                           |
| ---------------------- | -------------------------------------------------------------- |
| RAG Pipeline Deep-Dive | `workspaces/mingai/01-analysis/01-research/04-rag-pipeline.md` |
| MCP Servers            | `workspaces/mingai/01-analysis/01-research/06-mcp-servers.md`  |

---

**Document Version**: 1.0
**Analysis Completion**: 2026-03-04
