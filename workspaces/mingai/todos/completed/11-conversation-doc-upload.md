# TODO-11: Conversation Document Upload Endpoint

**Status**: COMPLETE
**Priority**: HIGH
**Owner**: Backend + Frontend
**Estimated Effort**: 3–4 days (BE: 2.5 days, FE: 1 day)
**Created**: 2026-03-18
**Red-teamed**: 2026-03-18 (v2 — critical issues C-1, C-2, C-3 fixed)

**Completed**: 2026-03-18
**Commit**: e63b4bc

**Evidence**: 11 unit tests + 5 integration tests passing. Security review (approved, HIGH findings tracked). Gold standards validator (passed). TypeScript clean (0 errors). Docs updated.

All 9 BE subtasks and 4 FE subtasks implemented and verified.

---

## Description

The `DocumentIndexingPipeline` in `src/backend/app/modules/documents/indexing.py`
already implements the full parse-chunk-embed-upsert pipeline and is tested. However
there is no HTTP surface to invoke it for end-user-uploaded files. End users cannot
attach a document to a conversation via the API.

This todo covers:

1. A new backend route `POST /api/v1/conversations/{conv_id}/documents`
2. Orchestrator changes so uploaded conversation chunks are actually retrieved in
   follow-up queries (the search call must target the conversation index)
3. A cascade delete path so chunks are cleaned up when a conversation is deleted
4. Backend integration tests (Tier 2, real PostgreSQL, no mocking)
5. Frontend: file upload button, progress indicator, success chip

---

## Critical Design Decisions (Red Team Findings)

### C-1 — Orchestrator Search Gap (CRITICAL — was incorrectly marked DONE in v1)

The orchestrator currently issues ONE search against `index_id = f"{tenant_id}-{agent_id}"`.
Conversation-uploaded chunks are stored in `index_id = f"conv-{tenant_id}-{conv_id}"`.
These two `index_id` values NEVER match. Uploaded chunks will **never appear in search
results** unless the orchestrator is updated to:

- Issue a second search against `f"conv-{tenant_id}-{conv_id}"` (with `conv_id` filter)
- Merge both result lists before RRF scoring or simply concatenate and re-rank

This is addressed in **BE-8** (new task).

> **v1 was wrong**: Line 102 of the original todo claimed "VectorSearchService.search()
> already passes conversation_id filter — uploaded chunks will be retrieved
> automatically." This is false. The orchestrator never passes `conversation_id` to
> `VectorSearchService.search()`. The SQL supports it but the value is never provided.

### C-2 — Orphaned Chunks on Conversation Delete (CRITICAL)

The `search_chunks.conversation_id` column has no FK constraint and no `ON DELETE CASCADE`.
Deleting a conversation orphans all its uploaded chunks permanently. This is addressed
in **BE-9** (new task): add a `DELETE FROM search_chunks WHERE conversation_id = :conv_id`
call in `delete_conversation()` in `chat/routes.py`.

### C-3 — Ambiguous `index_id` Format (CRITICAL)

Using `"{tenant_id}-{conv_id}"` for conversation indexes is ambiguous — it is
syntactically identical to integration indexes `"{tenant_id}-{integration_id}"`.
**All conversation uploads MUST use the prefix `"conv-"`**:

```
index_id = f"conv-{tenant_id}-{conv_id}"    # conversation uploads
index_id = f"{tenant_id}-{agent_id}"         # KB/integration search (unchanged)
```

The `conv-` prefix is:

- Semantically unambiguous in `search_index_registry`
- Safe (only hex, hyphens, and the literal string `"conv-"`)
- Easily filterable by admin tooling

---

## Gap Analysis

### What already exists

| Asset                                  | Location                                           | Notes                                                    |
| -------------------------------------- | -------------------------------------------------- | -------------------------------------------------------- |
| `DocumentIndexingPipeline`             | `src/backend/app/modules/documents/indexing.py`    | `process_file()` — full parse/chunk/embed/upsert         |
| `VectorSearchService.upsert_chunks()`  | `src/backend/app/modules/chat/vector_search.py`    | Supports `conversation_id`, `user_id` fields             |
| `PgVectorSearchClient.upsert_chunks()` | same file                                          | Bulk upsert; idempotent; updates `search_index_registry` |
| `EmbeddingService.embed()`             | `src/backend/app/modules/chat/embedding.py`        | Azure OpenAI / OpenAI, Redis-cached                      |
| Chat ownership checks                  | `src/backend/app/modules/chat/routes.py`           | `WHERE id=:id AND user_id=:user_id AND tenant_id=:tid`   |
| File attach button (inert)             | `src/web/components/chat/ChatInput.tsx` line 90–95 | `<Paperclip>` renders but no `onClick` / file input      |
| `search_chunks` schema                 | `alembic/versions/v041_search_chunks.py`           | Has `conversation_id UUID`, `user_id UUID`, `index_id`   |

### What is missing (after red team)

- HTTP route: `POST /api/v1/conversations/{conv_id}/documents`
- `VectorSearchService.upsert_conversation_chunks()` adapter (new index_id prefix)
- `DocumentIndexingPipeline.process_conversation_file()` (no sync_jobs writes, batched)
- **Orchestrator**: second search against conversation `index_id` merged into results
- **Delete path**: `DELETE FROM search_chunks WHERE conversation_id = :conv_id` in
  `delete_conversation()`
- Integration tests (Tier 2) for the new endpoint
- Frontend: wire `<Paperclip>`, upload hook, progress bar, success chip

---

## Acceptance Criteria

- [ ] `POST /api/v1/conversations/{conv_id}/documents` returns HTTP 200 with
      `{"conversation_id": "...", "file_name": "...", "chunks_indexed": N, "index_id": "conv-..."}`
- [ ] Chunks are stored with `index_id = f"conv-{tenant_id}-{conv_id}"`
- [ ] Authenticated end users can upload PDF, DOCX, PPTX, TXT files up to 20 MB
- [ ] Uploading to a conversation owned by a different user returns HTTP 404
- [ ] Cross-tenant upload attempt returns HTTP 403 or 404
- [ ] Unsupported file type (e.g. `.xlsx`) returns HTTP 422 with accepted types listed
- [ ] File exceeding 20 MB returns HTTP 413
- [ ] `search_index_registry` is updated with correct `chunk_count` and `doc_count`
- [ ] **Follow-up chat queries on the same conversation return chunks from the uploaded
      document** (orchestrator issues conversation-scoped second search)
- [ ] Deleting a conversation also deletes its `search_chunks` rows
- [ ] Tier 2 integration tests pass against real PostgreSQL (no mocking of DB)
- [ ] Frontend file-upload button opens OS file picker filtered to accepted MIME types
- [ ] Upload progress indicator visible while request is in flight
- [ ] Success chip shows file name and chunk count in DM Mono
- [ ] Oversized / unsupported files show inline error (not a toast)
- [ ] 0 TypeScript errors introduced

---

## Dependencies

- `DocumentIndexingPipeline` — already complete; new method needed (`process_conversation_file`)
- `PgVectorSearchClient.upsert_chunks()` — no changes needed
- `search_chunks` table — already has `conversation_id UUID`, `user_id UUID` columns
- `search_index_registry` — auto-updated by `upsert_chunks()`
- **Orchestrator** — must be updated (BE-8); currently does NOT pass `conversation_id`
- **`chat/routes.py` `delete_conversation()`** — must be updated (BE-9)

---

## Risk Assessment

| ID  | Risk                                                                    | Severity | Mitigation                                           |
| --- | ----------------------------------------------------------------------- | -------- | ---------------------------------------------------- |
| C-1 | Uploaded chunks unreachable in search (wrong index_id, missing conv_id) | CRITICAL | BE-8: orchestrator second search                     |
| C-2 | Orphaned search_chunks on conversation delete                           | CRITICAL | BE-9: explicit DELETE in delete_conversation         |
| C-3 | Ambiguous index_id format                                               | CRITICAL | Use `conv-` prefix throughout                        |
| H-1 | 20 MB read fully into memory before size check (DoS)                    | HIGH     | Read in 64 KB chunks; abort on limit                 |
| H-2 | Sync text extraction blocks event loop                                  | HIGH     | `asyncio.to_thread()` for extraction                 |
| H-3 | No user_id filter in orchestrator search                                | HIGH     | Document single-user conv assumption                 |
| H-4 | doc_count undercount for same-name files                                | HIGH     | `source_file_id = f"conv_{conv_id}_{safe_filename}"` |
| H-5 | Per-chunk DB transactions (N commits for N chunks)                      | HIGH     | Build full list; call `upsert_chunks()` once         |
| M-1 | No upload rate limiting                                                 | MEDIUM   | Note for ops config                                  |
| M-2 | No text-length cap after extraction (zip bomb)                          | MEDIUM   | Cap extracted text at 1M chars                       |
| M-3 | chunk_key contains raw filename                                         | MEDIUM   | Hash or sanitise filename component                  |
| M-4 | Missing idempotency test                                                | MEDIUM   | Add to test suite                                    |
| M-5 | Empty file returns 200 with 0 chunks                                    | MEDIUM   | Return 422 "File is empty"                           |

---

## Subtasks

### Backend

#### BE-1: Design constants and naming (Est: 15 min)

Define in `document_routes.py` (top of file):

```python
_CONV_INDEX_PREFIX = "conv-"
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # 20 MB
_MAX_TEXT_CHARS = 1_000_000             # zip bomb guard
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

def _conv_index_id(tenant_id: str, conv_id: str) -> str:
    return f"conv-{tenant_id}-{conv_id}"

def _conv_chunk_key(conv_id: str, safe_filename: str, chunk_index: int) -> str:
    # Hash filename to avoid special-char issues in chunk_key
    name_hash = hashlib.sha256(safe_filename.encode()).hexdigest()[:12]
    return f"conv_{conv_id}_{name_hash}_{chunk_index}"
```

Verification: constants documented; no production code changed yet.

#### BE-2: Add `upsert_conversation_chunks()` to `VectorSearchService` (Est: 45 min)

New method: accepts `tenant_id`, `conversation_id`, `user_id`, `file_name`, `chunks`
(list of `{text, embedding}` dicts). Builds chunk dicts with:

- `index_id = f"conv-{tenant_id}-{conversation_id}"`
- `source_type = "conversation"`
- `conversation_id = conversation_id`
- `user_id = user_id`
- `safe_filename = os.path.basename(file_name)[:255]` — derive at top of method
- `source_file_id = f"conv_{conversation_id}_{safe_filename}"` (unique per upload — fixes H-4)
- `chunk_key = _conv_chunk_key(conv_id, safe_filename, i)` for each chunk

Calls `self._client.upsert_chunks(chunk_list)` ONCE (fixes H-5 — not per-chunk).

Verification: unit test confirms chunk dicts; one upsert_chunks call per invocation.

#### BE-3: Add `process_conversation_file()` to `DocumentIndexingPipeline` (Est: 1h)

New async method:

1. Validate extension
2. Extract text via `asyncio.to_thread(self._extract_text_<ext>, path)` (fixes H-2)
3. Cap extracted text at `_MAX_TEXT_CHARS` chars (fixes M-2)
4. Chunk text (`_chunk_text`)
5. For each chunk: `await EmbeddingService.embed(chunk_text, tenant_id)`
6. Call `VectorSearchService.upsert_conversation_chunks(...)` with full list (fixes H-5)
7. Do NOT write to `sync_jobs`
8. Return `{"chunks_indexed": N, "file_name": basename, "conversation_id": ..., "index_id": ...}`

Verification: unit test; `sync_jobs` never written; `asyncio.to_thread` used for extraction.

#### BE-4: Create `src/backend/app/modules/chat/document_routes.py` (Est: 1.5h)

```
POST /conversations/{conversation_id}/documents
```

Flow:

1. Validate auth (end-user scope, not platform)
2. Read upload in 64 KB chunks up to `_MAX_UPLOAD_BYTES`; raise HTTP 413 if exceeded (fixes H-1)
3. Validate extension; raise HTTP 422 with accepted list if unsupported
4. Validate empty content (`len(content) == 0` → raise HTTP 422 "File is empty") (fixes M-5)
5. Ownership check: `WHERE id=:conv_id AND user_id=:user_id AND tenant_id=:tenant_id` → 404 if missing
6. Write to `tempfile.NamedTemporaryFile(delete=False, suffix=ext)`
7. Call `DocumentIndexingPipeline().process_conversation_file(...)`
8. `os.unlink(tmp_path)` in `finally`
9. Return 200 JSON

Security:

- `os.path.basename()` + 255-char limit on filename
- Do not log raw file contents
- `index_id` uses constant helper (no f-string DDL)

Verification: all HTTP error codes reachable; no bare `except: pass`.

#### BE-5: Register router in `src/backend/app/api/router.py` (Est: 15 min)

```python
from app.modules.chat.document_routes import router as doc_upload_router
router.include_router(doc_upload_router)
```

Verification: `GET /openapi.json` includes the new path.

#### BE-6: Integration tests `test_conversation_doc_upload.py` (Est: 2h)

Tier 2 — real PostgreSQL. Mock only `EmbeddingService.embed()` (returns `[0.1]*1536`).

Test cases:

- `test_upload_txt_success` — HTTP 200, row in `search_chunks` with correct fields
- `test_upload_pdf_success` — HTTP 200
- `test_upload_unsupported_type` — HTTP 422
- `test_upload_wrong_owner` — HTTP 404
- `test_upload_cross_tenant` — HTTP 403 or 404
- `test_upload_oversized` — HTTP 413
- `test_upload_empty_file` — HTTP 422 "File is empty" (new — M-5)
- `test_upload_idempotent` — upload same file twice; chunk count does not double (new — M-4)
- `test_search_chunks_visible_after_upload` — `knn_search()` with conversation index returns result
- `test_delete_conversation_removes_chunks` — delete conv; verify search_chunks rows gone (new — C-2)

Total: 10 integration tests.

Verification: `pytest tests/integration/test_conversation_doc_upload.py -v` exits 0.

#### BE-7: Unit tests (Est: 45 min)

Add to `tests/unit/test_document_indexing.py`:

- `test_process_conversation_file_returns_correct_keys`
- `test_process_conversation_file_no_sync_jobs_write`
- `test_process_conversation_file_unsupported_extension_raises`
- `test_process_conversation_file_empty_text_raises`
- `test_process_conversation_file_calls_to_thread_for_extraction`

Add to new `tests/unit/test_vector_search_conversation.py`:

- `test_upsert_conversation_chunks_sets_conv_prefix_index_id`
- `test_upsert_conversation_chunks_single_db_call` (H-5 regression guard)

Verification: all unit tests exit 0.

#### BE-8 (NEW — C-1 FIX): Update orchestrator to search conversation index (Est: 1.5h)

**File**: `src/backend/app/modules/chat/orchestrator.py`

The orchestrator already receives `conversation_id: str | None` (line 86). It must
additionally query the conversation index when a `conversation_id` is present:

```python
# Existing KB search
kb_results = await self._vector_search.search(
    query_vector=query_vector,
    tenant_id=tenant_id,
    agent_id=agent_id,
    query_text=query,
)

# Additional conversation-scoped search (only when conversation exists)
conv_results: list[SearchResult] = []
if conversation_id:
    conv_results = await self._vector_search.search_conversation_index(
        query_vector=query_vector,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        query_text=query,
        top_k=top_k,
    )

# Merge, re-sort by score (both use same RRF normalization), trim to top_k
search_results = sorted(
    kb_results + conv_results, key=lambda r: r.score, reverse=True
)[:top_k]
```

The post-merge sort+trim is required: without it, the merged list could have up to
`2 * top_k` results and overflow the LLM context window budget.

Add `search_conversation_index()` to `VectorSearchService`:

```python
async def search_conversation_index(
    self,
    *,
    query_vector: list[float],
    tenant_id: str,
    conversation_id: str,
    query_text: str | None = None,
    top_k: int = 5,
) -> list[SearchResult]:
    index_id = f"conv-{tenant_id}-{conversation_id}"
    raw = await self._client.knn_search(
        index_id=index_id,
        vector=query_vector,
        top_k=top_k,
        query_text=query_text,
        tenant_id=tenant_id,
        conv_id=conversation_id,
    )
    return [SearchResult(**r) for r in raw]
```

Verification: unit test confirms two search calls are made when `conversation_id` is
set; KB-only search unchanged when no `conversation_id`.

#### BE-9 (NEW — C-2 FIX): Delete conversation chunks on conversation delete (Est: 30 min)

**File**: `src/backend/app/modules/chat/routes.py`, `delete_conversation()` function

Add before the conversation DELETE:

```python
await session.execute(
    text("DELETE FROM search_chunks WHERE conversation_id = CAST(:conv_id AS uuid) AND tenant_id = CAST(:tid AS uuid)"),
    {"conv_id": conversation_id, "tid": tenant_id},
)
```

Also add the same cleanup to `delete_all_conversations()` / bulk delete if it exists.

Verification: integration test `test_delete_conversation_removes_chunks` passes.

---

### Frontend

#### FE-1: Wire `<Paperclip>` button in `ChatInput.tsx` (Est: 1h)

- Hidden `<input type="file" accept=".pdf,.docx,.pptx,.txt" />`
- Client-side size + type validation before calling `onUpload`
- Inline error state (not toast)
- Guard states (two distinct cases):
  - `!conversationId && !isStreaming` → "Send your first message before attaching"
  - `!conversationId && isStreaming` → "Please wait for the response before attaching"
  - Both disable the upload button (race condition: SSE `done` event sets `conversationId`)
- Reset file input value after each selection

#### FE-2: Create `useUploadDocument` hook (Est: 1h)

- `FormData` POST to `/api/v1/conversations/{conversationId}/documents`
- `uploading`, `progress` (0/50/100 approximation), `error`, `reset` state
- Error translation: HTTP 413 → "File too large (max 20 MB)", 422 → "Unsupported file type"
- Auth: use raw `fetch()` + `getStoredToken()` from `@/lib/auth` with
  `Authorization: Bearer ${token}`. Do NOT use `apiRequest()` from `@/lib/api` —
  it hardcodes `Content-Type: application/json` which breaks `multipart/form-data`
  boundary. Omit `Content-Type` header and let the browser set it with the boundary.

#### FE-3: Progress bar and success chip in `ChatInput.tsx` (Est: 45 min)

- Thin accent progress bar beneath input row while uploading
- Success chip: file name + `{chunksIndexed} chunks` in DM Mono + dismiss button
- Chip clears on message send
- Obsidian design system tokens throughout (no `shadow-lg`, no `rounded-2xl`)

#### FE-4: Thread `conversationId` from `ChatInterface` to `ChatInput` (Est: 30 min)

- `ChatInterface` → `ChatActiveState` → `ChatInput`: add `conversationId` prop
- `ChatInterface` → `ChatEmptyState` → `ChatInput`: add `conversationId` prop
- `handleUpload` in `ChatInterface` calls `uploadDocument(conversationId, file)`

---

## Testing Requirements

### Tier 1 (Unit — no I/O)

- [ ] `test_process_conversation_file_returns_correct_keys`
- [ ] `test_process_conversation_file_no_sync_jobs_write`
- [ ] `test_process_conversation_file_unsupported_extension_raises`
- [ ] `test_process_conversation_file_empty_text_raises`
- [ ] `test_process_conversation_file_calls_to_thread_for_extraction`
- [ ] `test_upsert_conversation_chunks_sets_conv_prefix_index_id`
- [ ] `test_upsert_conversation_chunks_single_db_call`
- [ ] `test_orchestrator_issues_conv_search_when_conv_id_present`

### Tier 2 (Integration — real PostgreSQL)

- [ ] `test_upload_txt_success`
- [ ] `test_upload_pdf_success`
- [ ] `test_upload_unsupported_type`
- [ ] `test_upload_wrong_owner`
- [ ] `test_upload_cross_tenant`
- [ ] `test_upload_oversized`
- [ ] `test_upload_empty_file`
- [ ] `test_upload_idempotent`
- [ ] `test_search_chunks_visible_after_upload`
- [ ] `test_delete_conversation_removes_chunks`

### Tier 3 (E2E — deferred until Tier 1 + 2 green)

- Upload `.txt` via chat UI in headed browser
- Assert success chip with file name and chunk count
- Send chat message referencing uploaded content
- Assert response cites the uploaded document

---

## Definition of Done

- [ ] All Tier 1 unit tests pass
- [ ] All Tier 2 integration tests pass
- [ ] `GET /openapi.json` includes `POST /api/v1/conversations/{conversation_id}/documents`
- [ ] Manual test: upload PDF to active conversation; follow-up query retrieves chunk from doc
- [ ] Deleting the conversation removes all its `search_chunks` rows
- [ ] 0 TypeScript errors
- [ ] No new `shadow-lg`, `rounded-2xl`, or hardcoded hex colours in FE
- [ ] No stub/TODO markers in production code
- [ ] intermediate-reviewer sign-off on all changed files
- [ ] security-reviewer sign-off before commit

---

## File Change Map

| File                                                            | Change Type                                                       | Subtask    |
| --------------------------------------------------------------- | ----------------------------------------------------------------- | ---------- |
| `src/backend/app/modules/documents/indexing.py`                 | Add `process_conversation_file()`                                 | BE-3       |
| `src/backend/app/modules/chat/vector_search.py`                 | Add `upsert_conversation_chunks()`, `search_conversation_index()` | BE-2, BE-8 |
| `src/backend/app/modules/chat/document_routes.py`               | New file — upload endpoint                                        | BE-4       |
| `src/backend/app/modules/chat/orchestrator.py`                  | Second search against conversation index                          | BE-8       |
| `src/backend/app/modules/chat/routes.py`                        | Add chunk delete in `delete_conversation()`                       | BE-9       |
| `src/backend/app/api/router.py`                                 | Register `doc_upload_router`                                      | BE-5       |
| `src/backend/tests/unit/test_document_indexing.py`              | Add `TestProcessConversationFile` tests                           | BE-7       |
| `src/backend/tests/unit/test_vector_search_conversation.py`     | New — upsert + orchestrator unit tests                            | BE-7       |
| `src/backend/tests/integration/test_conversation_doc_upload.py` | New — 10 integration tests                                        | BE-6       |
| `src/web/components/chat/ChatInput.tsx`                         | Wire Paperclip, file input, progress, chip                        | FE-1, FE-3 |
| `src/web/hooks/useUploadDocument.ts`                            | New — upload hook                                                 | FE-2       |
| `src/web/components/chat/ChatActiveState.tsx`                   | Forward `conversationId` + `onUpload`                             | FE-4       |
| `src/web/components/chat/ChatEmptyState.tsx`                    | Forward `conversationId` + `onUpload`                             | FE-4       |
| `src/web/components/chat/ChatInterface.tsx`                     | Thread `conversationId`, wire `handleUpload`                      | FE-4       |
