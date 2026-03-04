# 20. Document Upload Architecture

## 1. Frontend Drag-and-Drop Implementation

The chat page (`src/frontend/src/app/chat/page.tsx`) implements page-level drag-and-drop by attaching four event handlers to the outermost `<div>` wrapping the entire chat area:

```tsx
<div
  className="flex h-[calc(100dvh-56px)] flex-col relative"
  onDragEnter={handleDragEnter}
  onDragLeave={handleDragLeave}
  onDragOver={handleDragOver}
  onDrop={handleDrop}
>
```

### Drag Counter Pattern

A `dragCounterRef` (useRef) tracks nested drag enter/leave events to prevent flicker when dragging over child elements:

- **handleDragEnter**: Increments the counter. If `e.dataTransfer.types` includes `"Files"`, sets `isDraggingOver = true` to show the drop overlay. Works even without an active conversation (one will be auto-created).
- **handleDragLeave**: Decrements the counter. When it reaches 0, hides the overlay.
- **handleDragOver**: Calls `preventDefault()` to allow dropping (browser default is to deny drops).
- **handleDrop**: Resets counter to 0, hides overlay, reads the dropped file from `e.dataTransfer.files`, and triggers the upload flow.

### Full-Screen Drop Overlay

When `isDraggingOver` is true, a full-screen overlay renders with:

```tsx
<div className="absolute inset-0 z-50 flex items-center justify-center
  bg-background/80 backdrop-blur-sm border-2 border-dashed border-primary
  rounded-lg m-2">
```

Visual elements:

- Document emoji icon (large)
- "Drop file to upload" heading
- Supported file types hint: "PDF, Word, Excel, PowerPoint, TXT, or CSV"
- If no active conversation: "(A new conversation will be created)" subtext

---

## 2. Clipboard Paste Handler

### Global Paste Event Listener

The chat page registers a global paste listener on `document` using a stable ref pattern to avoid re-registration:

```tsx
// Ref to hold latest callback (updated on every render)
const handlePasteRef = useRef(handlePaste);
useEffect(() => {
  handlePasteRef.current = handlePaste;
}, [handlePaste]);

// Register once on mount - never re-registers
useEffect(() => {
  const handlePasteEvent = (e: Event) => {
    handlePasteRef.current(e as ClipboardEvent);
  };
  document.addEventListener("paste", handlePasteEvent);
  return () => document.removeEventListener("paste", handlePasteEvent);
}, []);
```

### Clipboard Image Detection

The `handlePaste` callback processes clipboard items:

1. Guards against paste during active upload (`isUploading` check).
2. Iterates `e.clipboardData.items`, prioritizing `image/*` types (screenshots paste as `image/png`).
3. Falls back to any `kind === "file"` item.
4. If the target is an input/textarea and no file/image is found, allows default paste (text into field).
5. If a file is found, calls `e.preventDefault()` and proceeds.

### Processing Pasted Images

- Converts `DataTransferItem` to `File` via `getAsFile()`.
- Generates a meaningful filename for clipboard images: `clipboard-YYYYMMDD-HHMMSS.{ext}` (e.g., `clipboard-20240124-103045.png`). Handles MIME types like `image/svg+xml` by extracting the base format (`svg`).
- Validates file type BEFORE creating a conversation (prevents orphan conversations on unsupported types).
- Creates a new `File` object with the generated name (since `File` objects are immutable).
- If no active conversation exists, creates one titled `"Chat about {filename}"`.
- Uploads using the same `uploadDocument()` hook as drag-and-drop.

---

## 3. Upload Hook (`useDocumentUpload`)

**File**: `src/frontend/src/hooks/useDocumentUpload.ts`

### Interface

```typescript
export function useDocumentUpload(): {
  uploadDocument: (
    file: File,
    conversationId: string,
  ) => Promise<ConversationDocument>;
  uploadProgress: UploadProgress | null;
  isUploading: boolean;
  reset: () => void;
};
```

### FormData Construction

```typescript
const formData = new FormData();
formData.append("file", file);
```

Headers include:

- `Authorization: Bearer {jwt}` from `getToken()`
- `X-CSRF-Token: {csrf}` from `getCsrfToken()`
- No explicit `Content-Type` header (browser sets multipart boundary automatically)

### POST Request with SSE Streaming Response

```typescript
const response = await fetch(
  `${API_BASE_URL}/v1/conversations/${conversationId}/documents`,
  { method: "POST", headers, credentials: "include", body: formData },
);
```

The response is a `text/event-stream` (SSE). The hook reads it with:

```typescript
const reader = response.body.getReader();
const decoder = new TextDecoder();
```

SSE events are parsed line-by-line (`data: {...}\n\n` format). Each event has the shape:

```typescript
interface UploadSSEEvent {
  type: "upload_progress";
  stage: UploadStage | "complete" | "failed";
  progress: number;
  message?: string;
  document?: ConversationDocument;
  error?: string;
}
```

### Progress State Management

- `uploadProgress` state is set on each SSE event with `{ stage, progress }`.
- On `"complete"`: Sets progress to 100 and captures the returned `ConversationDocument`.
- On `"failed"`: Sets error and throws to the caller.
- After upload completes or fails, `setIsUploading(false)` is called in `finally` block.
- Progress auto-clears after 3 seconds via `setTimeout(() => setUploadProgress(null), 3000)`.

### Error Handling

User-facing error messages are generated by `getFriendlyErrorMessage()`:

| Raw Error Pattern                 | Friendly Message                                            |
| --------------------------------- | ----------------------------------------------------------- |
| `RateLimitError`, `429`           | "Too many files uploaded at once. Please wait a minute..."  |
| `timeout`, `Timeout`              | "Upload timed out. Please try again with a smaller file..." |
| `NetworkError`, `Failed to fetch` | "Network error. Please check your connection..."            |
| `quota`, `Quota`                  | "Service quota exceeded. Please try again later..."         |
| (no match)                        | Original error message passed through                       |

### Client-Side Validation (Pre-Upload)

Before sending the request, the hook validates:

1. `conversationId` is non-empty.
2. File type is supported via `isSupportedFileType(file.name)`.
3. File size is under `MAX_FILE_SIZE_BYTES` (30 MB).

---

## 4. Upload Stages

The pipeline progresses through these stages, defined in `SSEUploadProgressEvent`:

| Stage               | Progress            | What Happens                                                                                        | Error Conditions                                                                                           |
| ------------------- | ------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `validating`        | 0-10%               | File type, size, filename length, content-type match, conversation ownership, document count limit  | Invalid type, size > 30MB, filename > 255 chars, content-type mismatch, conversation not found, >= 20 docs |
| `uploading`         | 50%                 | File bytes uploaded to Azure Blob Storage at path `{user_id}/{conversation_id}/{filename}`          | Azure Storage errors, connection timeout                                                                   |
| `extracting`        | 35% (background)    | HybridExtractionService routes to appropriate extractor by file type                                | Extraction library errors, corrupt files                                                                   |
| `extracting_images` | 35% (background)    | Images extracted from PDF/PPTX/DOCX via ImageExtractionService                                      | No extractable images (graceful skip)                                                                      |
| `analyzing_images`  | 45-50% (background) | Vision API generates descriptions for extracted images (max concurrent: config)                     | Vision API timeout, rate limits                                                                            |
| `chunking`          | (background)        | SemanticChunker creates type-aware chunks (slides, tables, sections)                                | Empty content                                                                                              |
| `embedding`         | (background)        | text-embedding-3-large generates 3072-dim vectors per chunk                                         | OpenAI API errors                                                                                          |
| `indexing`          | 80%                 | Chunks indexed in Azure AI Search with vectors                                                      | Search API errors                                                                                          |
| `complete`          | 100%                | Document metadata saved to conversation record with `status: "processing"`, background task spawned | -                                                                                                          |
| `failed`            | 0%                  | Error message sent, blob cleaned up if uploaded, document status set to "failed"                    | Any unhandled exception                                                                                    |

**Architecture note**: The upload endpoint returns `complete` at 100% after blob upload and document record creation. The actual extraction, chunking, embedding, and indexing happen in a background `asyncio.Task`. The document initially has `status: "processing"` and transitions to `"ready"` or `"failed"` asynchronously. Chat waits for document to be `"ready"` before searching it.

---

## 5. File Limits

| Limit                            | Value                                                | Enforcement Location                                                                   |
| -------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Max file size                    | 30 MB (`MAX_FILE_SIZE_BYTES = 30 * 1024 * 1024`)     | Frontend: `useDocumentUpload` pre-check. Backend: `document_router.py` post-read check |
| Max documents per conversation   | 20 (`MAX_DOCUMENTS_PER_CONVERSATION`)                | Backend: `validate_file()` in `document_router.py`                                     |
| Max filename length              | 255 characters (`MAX_FILENAME_LENGTH`)               | Backend: `validate_file()` + `sanitize_filename()`                                     |
| Max images per document (vision) | Config-driven (`settings.vision_max_images_per_doc`) | Backend: `_process_vision()` in `document_extraction.py`                               |

### Supported MIME Types (Tiered)

**Tier 1 -- Office Documents**: `pdf`, `docx`, `doc`, `xlsx`, `xls`, `pptx`, `ppt`

**Tier 2 -- Plain Text**: `csv`, `txt`, `md`

**Tier 3 -- Web/Data Formats**: `html`, `htm`, `json`, `xml`, `eml`

**Tier 4 -- Images (Vision Recognition)**: `jpg`, `jpeg`, `png`, `bmp`, `tiff`, `gif`, `webp`

Content-type verification prevents extension spoofing (e.g., a `.pdf` with `image/jpeg` content-type is rejected).

---

## 6. Backend Pipeline

### Endpoint

```
POST /v1/conversations/{conversation_id}/documents
```

Returns `StreamingResponse` with `media_type="text/event-stream"`.

### MIME Type Validation

The `verify_content_type()` function checks that the `Content-Type` header matches the expected type for the file extension. A mapping (`ALLOWED_CONTENT_TYPES`) defines acceptable content types per extension. Mismatches are rejected with HTTP 400.

### Filename Sanitization

`sanitize_filename()` provides path traversal protection:

1. Strips path components via `os.path.basename()`.
2. Removes null bytes.
3. Replaces non-alphanumeric characters (except `-` and `_`) with underscores.
4. Truncates name to fit within 255 characters including extension.

### Azure Blob Storage

**Service**: `BlobStorageService` (`src/backend/api-service/app/services/blob_storage.py`)

**Path structure**: `{user_id}/{conversation_id}/{filename}`

**Container**: Configured via `settings.azure_blob_container_name` (auto-created if not exists).

**Upload**: Uses `azure.storage.blob.aio.BlobServiceClient` with `overwrite=True`. Metadata attached: `user_id`, `conversation_id`, `uploaded_at`.

**Usage tracking**: Fire-and-forget `asyncio.create_task()` tracks upload/download/delete operations via `BlobUsageTracker` for analytics.

### HybridExtractionService Routing Logic

**Service**: `HybridExtractionService` (`src/backend/api-service/app/services/document_extraction.py`)

Routing is by file extension:

| Extension                                                 | Extraction Method             | Library                                                      |
| --------------------------------------------------------- | ----------------------------- | ------------------------------------------------------------ |
| `.pdf`                                                    | `_extract_with_azure_di()`    | Azure Document Intelligence (`prebuilt-layout` model)        |
| `.xlsx`, `.xls`                                           | `_extract_excel()`            | openpyxl (`data_only=True` for formula values)               |
| `.pptx`, `.ppt`                                           | `_extract_powerpoint()`       | python-pptx (text + speaker notes per slide)                 |
| `.docx`, `.doc`                                           | `_extract_word()`             | python-docx (paragraphs with styles + tables)                |
| `.txt`, `.csv`, `.md`                                     | `_extract_text()`             | Built-in (UTF-8 with latin-1 fallback; CSV parsed as table)  |
| `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.gif`, `.webp` | `_extract_standalone_image()` | PIL for dimensions, VisionDescriptionService for description |

For PDF, PPTX, and DOCX: if vision is enabled, `_process_vision()` runs after text extraction to extract embedded images (via `ImageExtractionService` from `aihub_shared`) and generate descriptions (via `VisionDescriptionService`).

### Vision Processing Integration

When enabled:

1. **Image extraction**: `ImageExtractionService.extract_from_{pdf,pptx,docx}()` pulls embedded images.
2. **Image limit**: Capped at `settings.vision_max_images_per_doc`.
3. **Description generation**: `TrackedVisionDescriptionService.describe_batch()` calls the Azure OpenAI vision deployment with concurrency controlled by `settings.vision_concurrent_requests`.
4. **Cost tracking**: Each vision API call is tracked via `LLMUsageTracker` with `operation="vision_description"`.
5. **Token estimation**: ~1265 input tokens (500 system + 765 image) and output tokens estimated at `len(description) / 4`.

### Chunking Strategy

**Service**: `SemanticChunker` (`src/backend/api-service/app/services/semantic_chunker.py`)

| Content Type           | Strategy                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------- |
| Presentation (PPTX)    | Each slide becomes one chunk. Includes title, body text, and speaker notes.               |
| Spreadsheet (XLSX/CSV) | Headers preserved in every chunk. 20 rows per chunk. Tables converted to markdown format. |
| Document (DOCX/PDF)    | Chunked by sections/headings. Sub-chunked if content exceeds 2000 characters.             |
| Plain text (TXT/MD)    | Generic text chunking with 2000-character limit.                                          |
| Standalone image       | Single chunk with vision description as content.                                          |
| Embedded images        | Image description chunks added alongside text chunks.                                     |

Recognized `chunk_type` values: `slide`, `table`, `section`, `text`, `content`, `image`.

### Embedding Generation

Embeddings are generated using `text-embedding-3-large` (3072 dimensions) via the `get_doc_embeddings_batch()` function. Each chunk's embedding generation time and token count are tracked via `LLMUsageTracker`.

### Azure AI Search Index

**Index name**: Configured via `settings.azure_search_conversation_docs_index` (typically `aihub-conversation-documents`).

**Service**: `ConversationDocumentSearchService` (`src/backend/api-service/app/services/document_search.py`)

**Document schema per chunk**:

- `id`: `{document_id}_{chunk_index}`
- `document_id`, `conversation_id`, `user_id`
- `chunk_index`, `file_type`, `chunk_type`
- `content`, `content_vector` (3072-dim)
- `document_name`, `uploaded_at`
- Type-specific fields: `sheet_name`, `row_range`, `slide_number`, `slide_title`, `section_heading`, `page_number`, `image_type`, `location`

### Per-User Isolation via Query-Time Filter

All search queries filter by BOTH `conversation_id` AND `user_id`:

```python
filter_parts = [
    f"conversation_id eq '{conversation_id}'",
    f"user_id eq '{user_id}'",
]
```

This ensures users can only search their own documents. There is no tenant-level isolation in the current single-tenant architecture.

---

## 7. Auto-Conversation Creation

### When Triggered

Auto-conversation creation occurs when a user drops a file or pastes an image and no `activeConversationId` exists (i.e., the user is on the empty chat screen).

### Flow

```typescript
// Drag-and-drop handler
if (!targetConversationId) {
  const conversation = await apiClient.post<{ id: string }>("/conversations/", {
    title: `Chat about ${file.name}`,
  });
  targetConversationId = conversation.id;
  setActiveConversationId(targetConversationId);
  setSidebarRefreshTrigger((prev) => prev + 1);
}
```

### Conversation Title Format

`"Chat about {filename}"` -- e.g., `"Chat about Q4_Revenue.xlsx"`.

### UI Integration

- `activeConversationId` is set immediately so the UI transitions from empty state to chat view.
- Sidebar refresh is triggered to show the new conversation in the list.
- `hasDocumentInSession` flag is set to prevent the UI from reverting to the empty state while the upload is in progress.
- The `isEmpty` check combines: `messages.length === 0 && !uploadProgress && !hasDocumentInSession`.

---

## 8. Attachment Management

### AttachmentPopover Component

**File**: `src/frontend/src/components/chat/AttachmentPopover.tsx`

The `AttachmentPopover` component is rendered in the `ChatInputToolbar` (below the chat input area) and provides a paperclip icon button that opens a popover listing attached documents.

### Document Badge

The paperclip button shows a badge with the document count:

- Blue badge with count when documents exist.
- Red icon color when any document has `status === "failed"`.
- Gray when empty.

### Document List

Each document displays:

- **File icon**: `FileText`, `FileSpreadsheet`, or `Presentation` based on `getFileTypeCategory()`.
- **Filename**: Truncated with tooltip for names > 30 characters.
- **Metadata line**: `{FILE_TYPE} . {size} . {extraction_summary}`.
- **Status badge**: Shown only for non-completed statuses (`"processing"`, `"failed"`).

### Extraction Summary

The `getExtractionSummary()` helper provides context-aware summaries:

- Spreadsheets: `"3 sheets"`
- Presentations: `"12 slides"`
- Documents with page count: `"5 pages"`
- Fallback: `"8 chunks"`

### Download Functionality

Downloads use the `blob_url` from the document record:

```typescript
const response = await fetch(doc.blob_url);
const blob = await response.blob();
const url = window.URL.createObjectURL(blob);
// Trigger download via invisible anchor element
```

### Delete Functionality

```typescript
await apiClient.delete(`/conversations/${conversationId}/documents/${docId}`);
```

Backend cascade on delete:

1. Remove document from conversation metadata (Cosmos DB).
2. Delete all chunks from Azure AI Search index (`delete_by_document_id()`).
3. Delete blob from Azure Blob Storage.

### Data Fetching

Documents are fetched via `GET /v1/conversations/{conversation_id}/documents` on:

- Conversation change (`conversationId` prop change).
- Refresh trigger (`refreshTrigger` prop increment, fired after upload complete).
- Popover open state change.

---

## 9. Multi-Tenant Gap Analysis

The current architecture is single-tenant. The following changes are required for multi-tenant support:

### Storage Path Needs `tenant_id` Prefix

**Current**: `{user_id}/{conversation_id}/{filename}`

**Required**: `{tenant_id}/{user_id}/{conversation_id}/{filename}`

This ensures blob storage paths are isolated per tenant. The `BlobStorageService.upload_file()` method constructs the path inline and would need a `tenant_id` parameter.

### Search Index Needs Tenant Isolation

**Current**: Security is enforced via `user_id` filter at query time. There is no tenant-level isolation -- all users share the same Azure AI Search index (`aihub-conversation-documents`).

**Options**:

1. **Tenant-scoped filter (RLS-style)**: Add `tenant_id` field to the search index schema and include it in all queries. Simplest change, but all tenant data is in one index.

   ```python
   filter_parts = [
       f"tenant_id eq '{tenant_id}'",
       f"conversation_id eq '{conversation_id}'",
       f"user_id eq '{user_id}'",
   ]
   ```

2. **Per-tenant index**: Create separate indexes per tenant (`aihub-conv-docs-{tenant_id}`). Stronger isolation but higher operational overhead (index provisioning, scaling per tenant).

**Recommendation**: Start with option 1 (tenant-scoped filter) for MVP. Migrate to per-tenant indexes if noisy-neighbor or compliance requirements demand it.

### Blob Container Strategy

**Current**: Single container configured via `settings.azure_blob_container_name`.

**Options**:

1. **Tenant-prefixed paths** (path-based isolation): Single container, paths become `{tenant_id}/{user_id}/{conversation_id}/{filename}`. Simplest migration.

2. **Per-tenant containers**: Container name becomes `{base_name}-{tenant_id}`. Stronger isolation, enables per-tenant storage quotas and access policies. Higher operational complexity.

**Recommendation**: Tenant-prefixed paths for MVP. The `BlobStorageService` already uses prefix-based listing for deletion (`delete_conversation_folder()`), so adding a tenant prefix is a minimal change.

### Document Count Limits

**Current**: 20 documents per conversation (hardcoded `MAX_DOCUMENTS_PER_CONVERSATION`).

**Required**: Per-tenant configurable limits. Some tenants may need higher limits for enterprise use cases. Limit should be stored in tenant configuration and passed to `validate_file()`.

### File Size Limits

**Current**: 30 MB hardcoded (`MAX_FILE_SIZE_BYTES`).

**Required**: Per-tenant configurable. Premium tenants may need larger file uploads (e.g., 100 MB for large Excel files).

### Usage Tracking Needs `tenant_id`

Both `BlobUsageTracker` and `LLMUsageTracker` currently track by `user_id`. Multi-tenant mode requires `tenant_id` on all tracking calls for per-tenant cost analytics and billing.

### Background Task Cleanup

The `_background_tasks` dictionary in `document_router.py` tracks active background processing tasks. In multi-tenant mode, this would need tenant-aware cleanup on tenant deprovisioning or suspension.
