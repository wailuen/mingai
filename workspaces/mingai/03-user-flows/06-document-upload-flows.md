# Document Upload Flows

**Persona**: Knowledge Worker (End User)
**Scope**: Drag-and-drop upload, clipboard paste, mobile upload, auto-conversation creation, attachment management, error recovery
**Role**: `default` (scope: tenant) + custom index-access roles
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                  | Built in Phase | Notes                                                      |
| ---- | -------------------------- | -------------- | ---------------------------------------------------------- |
| 01   | Drag-and-Drop Upload       | Phase 1        | Full-screen overlay, SSE progress, multi-stage pipeline    |
| 02   | Clipboard Paste Upload     | Phase 1        | Screenshot/image paste detection, auto-filename generation |
| 03   | Mobile/Touch Upload        | Phase 1        | OS file picker, same pipeline as drag-and-drop             |
| 04   | Auto-Conversation Creation | Phase 1        | Upload without active conversation triggers creation       |
| 05   | Attachment Management      | Phase 1        | View, download, delete attached documents                  |
| 06   | Upload Error Recovery      | Phase 1        | Retry, graceful degradation, failure state management      |

---

## 1. Drag-and-Drop Upload

**Trigger**: User drags file(s) from desktop toward the browser chat window.

```
Start
  |
  v
[User drags file from desktop toward browser]
  |-- Browser fires dragenter event on chat area
  |-- dragCounterRef incremented to track nested elements
  |-- System checks e.dataTransfer.types includes "Files"
  |
  +-- NOT a file drag (text, URL) -> No overlay, default browser behavior
  |
  v
[Full-screen drop overlay appears]
  |-- Backdrop: bg-background/80 with backdrop-blur-sm
  |-- Border: 2px dashed primary color, rounded corners
  |-- Content: document emoji icon (large)
  |-- Heading: "Drop file to upload"
  |-- Subtext: "PDF, Word, Excel, PowerPoint, TXT, or CSV"
  |-- If no active conversation: "(A new conversation will be created)"
  |
  v
[User positions file over drop zone]
  |-- Visual state: valid drop target highlighted
  |-- dragover handler calls preventDefault() to allow drop
  |
  +-- User drags file away from browser window
  |     |-> dragCounterRef decrements to 0
  |     |-> Overlay hides
  |     |-> No action taken
  |
  v
[User drops file]
  |-- dragCounterRef reset to 0
  |-- Overlay hides immediately
  |-- File read from e.dataTransfer.files
  |
  v
[Client-side validation (useDocumentUpload hook)]
  |-- Check 1: File type supported? (isSupportedFileType)
  |   |-- Tier 1 (Office): pdf, docx, doc, xlsx, xls, pptx, ppt
  |   |-- Tier 2 (Text): csv, txt, md
  |   |-- Tier 3 (Web/Data): html, htm, json, xml, eml
  |   |-- Tier 4 (Images): jpg, jpeg, png, bmp, tiff, gif, webp
  |
  +-- INVALID TYPE -> "Unsupported file type. Supported: PDF, Word, Excel,
  |   PowerPoint, TXT, CSV, images, and more."
  |   |-> Upload aborted, no conversation created
  |
  |-- Check 2: File size <= 30 MB (MAX_FILE_SIZE_BYTES)?
  |
  +-- TOO LARGE -> "File exceeds 30 MB limit. Please try a smaller file."
  |   |-> Upload aborted
  |
  |-- Check 3: conversationId present? (or auto-create, see Flow 4)
  |
  v
[Upload request initiated]
  |-- POST /v1/conversations/{conversation_id}/documents
  |-- FormData with file attached
  |-- Headers: Authorization (Bearer JWT), X-CSRF-Token
  |-- No explicit Content-Type (browser sets multipart boundary)
  |
  v
[Backend validation (document_router.py)]
  |-- Filename sanitization: strip path, remove null bytes, replace special chars
  |-- Filename length <= 255 characters
  |-- Content-type verification: extension matches MIME type
  |   |-> Prevents extension spoofing (e.g., .pdf with image/jpeg rejected)
  |-- Document count check: conversation has < 20 documents
  |
  +-- >= 20 DOCUMENTS -> HTTP 400: "Maximum 20 documents per conversation reached."
  |
  +-- CONTENT-TYPE MISMATCH -> HTTP 400: "File content does not match extension."
  |
  v
[SSE progress stream begins]
  |-- Response: text/event-stream
  |-- Frontend reads via ReadableStream reader + TextDecoder
  |-- Each event: { type: "upload_progress", stage, progress, message }
  |
  v
[Stage: validating (0-10%)]
  |-- Server-side file validation complete
  |
  v
[Stage: uploading (50%)]
  |-- File bytes uploaded to Azure Blob Storage
  |-- Path: {user_id}/{conversation_id}/{filename}
  |-- Metadata: user_id, conversation_id, uploaded_at
  |
  v
[Stage: complete (100%) -- immediate response]
  |-- Document metadata saved to conversation record
  |-- Document status: "processing"
  |-- SSE sends complete event with ConversationDocument object
  |-- Frontend: file appears in attachment list
  |-- Progress auto-clears after 3 seconds
  |
  v
[Background processing (asyncio.Task)]
  |
  +-- Stage: extracting
  |   |-- HybridExtractionService routes by file extension:
  |   |   |-- PDF -> Azure Document Intelligence (prebuilt-layout)
  |   |   |-- XLSX/XLS -> openpyxl (data_only=True)
  |   |   |-- PPTX/PPT -> python-pptx (text + speaker notes)
  |   |   |-- DOCX/DOC -> python-docx (paragraphs + tables)
  |   |   |-- TXT/CSV/MD -> built-in (UTF-8 with latin-1 fallback)
  |   |   |-- Images -> PIL + VisionDescriptionService
  |
  +-- Stage: extracting_images
  |   |-- PDF/PPTX/DOCX: ImageExtractionService pulls embedded images
  |   |-- Capped at settings.vision_max_images_per_doc
  |   |-- No extractable images -> graceful skip (not an error)
  |
  +-- Stage: analyzing_images (45-50%)
  |   |-- Vision API generates descriptions for extracted images
  |   |-- Concurrency controlled by settings.vision_concurrent_requests
  |   |-- Cost tracked via LLMUsageTracker (operation: "vision_description")
  |
  +-- Stage: chunking
  |   |-- SemanticChunker creates type-aware chunks:
  |   |   |-- Presentations: one chunk per slide (title + body + notes)
  |   |   |-- Spreadsheets: headers preserved, 20 rows per chunk (markdown)
  |   |   |-- Documents: chunked by sections/headings (max 2000 chars)
  |   |   |-- Plain text: generic 2000-character chunks
  |   |   |-- Images: single chunk with vision description
  |
  +-- Stage: embedding
  |   |-- text-embedding-3-large generates 3072-dim vectors per chunk
  |   |-- Token count and generation time tracked via LLMUsageTracker
  |
  +-- Stage: indexing (80%)
  |   |-- Chunks indexed in Azure AI Search
  |   |-- Index: mingai-conversation-documents
  |   |-- Per-chunk fields: document_id, conversation_id, user_id,
  |   |   content, content_vector, chunk_type, metadata fields
  |
  v
[Document status transitions to "ready"]
  |-- Chat can now search this document
  |-- Attachment popover shows extraction summary
  |
  v
End
```

**Outcome**: Document uploaded, processed, and indexed. User can immediately ask questions about the document content.

---

## 2. Clipboard Paste Upload

**Trigger**: User has an image in clipboard (screenshot, copied image) and pastes in the chat window.

```
Start
  |
  v
[User copies image to clipboard]
  |-- Screenshot (OS screenshot tool)
  |-- Copy image from browser/application
  |-- Any image/* content in clipboard
  |
  v
[User presses Ctrl+V / Cmd+V in chat window]
  |
  v
[Global paste event listener fires]
  |-- Registered on document via useEffect (mount-once pattern)
  |-- Uses stable ref (handlePasteRef) to avoid re-registration
  |
  v
[Guard checks]
  |
  +-- Upload already in progress (isUploading)?
  |     |-> Paste ignored, current upload continues
  |
  +-- Target is input/textarea AND no image in clipboard?
  |     |-> Allow default paste behavior (text into field)
  |
  v
[Clipboard item detection]
  |-- Iterate e.clipboardData.items
  |-- Priority 1: image/* types (screenshots paste as image/png)
  |-- Priority 2: any kind === "file" item
  |
  +-- No file or image found -> Default paste behavior (text)
  |
  v
[e.preventDefault() called -- system handles the paste]
  |
  v
[File object created]
  |-- Convert DataTransferItem to File via getAsFile()
  |-- Generate filename: clipboard-YYYYMMDD-HHMMSS.{ext}
  |   |-- Example: clipboard-20260304-143022.png
  |   |-- MIME type image/svg+xml -> ext = svg
  |-- Create new File object with generated name
  |   (File objects are immutable, so a new instance is needed)
  |
  v
[Client-side validation]
  |-- File type check BEFORE conversation creation
  |   (prevents orphan conversations on unsupported types)
  |
  +-- UNSUPPORTED TYPE -> Error toast, no conversation created
  |
  v
[Auto-create conversation if needed]
  |-- If no activeConversationId:
  |   |-> POST /conversations/ with title: "Chat about clipboard-20260304-143022.png"
  |   |-> Set activeConversationId
  |   |-> Trigger sidebar refresh
  |
  v
[Upload via uploadDocument() hook]
  |-- Same SSE progress pipeline as drag-and-drop (Flow 1)
  |-- For images: extraction uses PIL + VisionDescriptionService
  |-- Single chunk created with vision description as content
  |
  v
[Success: image appears in attachment list]
  |-- Badge count incremented
  |-- Extraction summary: "1 image"
  |
  v
End
```

**Outcome**: Clipboard image uploaded and indexed with vision-generated description. User can ask questions about the image content.

---

## 3. Mobile/Touch Upload

**Trigger**: User taps file picker icon on a mobile or touch device.

```
Start
  |
  v
[User taps file picker icon in chat toolbar]
  |-- Icon visible in ChatInputToolbar
  |-- Same icon triggers OS-native file picker
  |
  v
[OS file picker opens]
  |-- iOS: Files app / Photos picker
  |-- Android: file manager / gallery
  |-- Supports same file types as desktop (Tiers 1-4)
  |
  v
[User selects file]
  |
  +-- User cancels picker -> No action taken
  |
  v
[File received by input handler]
  |-- Same File object as desktop drag-and-drop
  |
  v
[Client-side validation]
  |-- Same checks as Flow 1:
  |   |-- Supported file type
  |   |-- Size <= 30 MB
  |
  +-- INVALID -> Error toast displayed
  |
  v
[Auto-create conversation if needed (see Flow 4)]
  |
  v
[Upload via uploadDocument() hook]
  |-- Same SSE progress pipeline as Flow 1
  |-- Same backend processing stages
  |-- Progress displayed in chat area
  |
  v
[Success: file appears in attachment list]
  |
  v
End
```

**Error Paths**:

- Large file on slow mobile connection -> upload may timeout; user sees "Upload timed out. Please try again with a smaller file or on a faster connection."
- OS file picker returns unsupported format -> client-side validation rejects before upload attempt

---

## 4. Auto-Conversation Creation

**Trigger**: User uploads a file (via any method) when no active conversation exists.

```
Start
  |
  v
[Upload triggered without activeConversationId]
  |-- User is on empty chat screen (no conversation selected)
  |-- Applies to: drag-and-drop, clipboard paste, file picker
  |
  v
[File type validation runs FIRST]
  |-- Ensures no orphan conversation on invalid file
  |
  +-- INVALID FILE -> Error shown, NO conversation created
  |
  v
[Create conversation via API]
  |-- POST /conversations/
  |-- Payload: { title: "Chat about {filename}" }
  |   |-- Example: "Chat about Q4_Revenue.xlsx"
  |   |-- Example: "Chat about clipboard-20260304-143022.png"
  |
  v
[API returns conversation object with id]
  |
  v
[UI state updates]
  |-- setActiveConversationId(conversation.id)
  |   |-> UI transitions from empty state to chat view
  |-- setSidebarRefreshTrigger(prev => prev + 1)
  |   |-> New conversation appears in sidebar list
  |-- setHasDocumentInSession(true)
  |   |-> Prevents UI from reverting to empty state during upload
  |   |-> isEmpty check: messages.length === 0 && !uploadProgress && !hasDocumentInSession
  |
  v
[Upload proceeds with new conversationId]
  |-- Same pipeline as Flow 1 (stages: validating -> uploading -> ... -> complete)
  |
  v
[User lands in new conversation with document attached]
  |-- Chat input ready for questions about the document
  |-- Attachment badge shows document count
  |
  v
End
```

**Outcome**: Seamless upload experience -- user does not need to manually create a conversation before uploading.

---

## 5. Attachment Management

**Trigger**: User clicks attachment indicator (paperclip badge) on the chat input toolbar.

### Viewing Attachments

```
Start
  |
  v
[User sees paperclip icon in ChatInputToolbar]
  |-- Badge indicator:
  |   |-- Blue badge with count -> documents attached
  |   |-- Red icon color -> at least one document has status "failed"
  |   |-- Gray (no badge) -> no documents attached
  |
  v
[User clicks paperclip icon]
  |
  v
[AttachmentPopover opens]
  |-- Fetches documents: GET /v1/conversations/{conversation_id}/documents
  |-- Refresh triggers: conversation change, upload complete, popover open
  |
  v
[Document list displayed]
  |-- For each document:
  |   |-- File icon: FileText (docs), FileSpreadsheet (xlsx), Presentation (pptx)
  |   |-- Filename: truncated at 30 chars with tooltip for full name
  |   |-- Metadata line: "{FILE_TYPE} . {size} . {extraction_summary}"
  |   |-- Status badge (only for non-complete): "processing" or "failed"
  |
  |-- Extraction summaries (context-aware):
  |   |-- Spreadsheets: "3 sheets"
  |   |-- Presentations: "12 slides"
  |   |-- Documents with pages: "5 pages"
  |   |-- Fallback: "8 chunks"
  |
  v
End
```

### Downloading an Attachment

```
Start
  |
  v
[User clicks download action on a document in AttachmentPopover]
  |
  v
[Fetch blob URL]
  |-- GET request to doc.blob_url (Azure Blob Storage signed URL)
  |
  v
[Create object URL from response blob]
  |-- const blob = await response.blob()
  |-- const url = window.URL.createObjectURL(blob)
  |
  v
[Trigger download via invisible anchor element]
  |-- Opens in new tab / triggers browser download dialog
  |-- Original filename preserved
  |
  v
End
```

### Deleting an Attachment

```
Start
  |
  v
[User clicks delete action on a document in AttachmentPopover]
  |
  v
[Confirmation prompt displayed]
  |-- "Delete {filename}? This will remove the document and its indexed content."
  |
  +-- User cancels -> No action
  |
  v
[DELETE /v1/conversations/{conversation_id}/documents/{document_id}]
  |
  v
[Backend cascade]
  |-- Step 1: Remove document from conversation metadata (Cosmos DB)
  |-- Step 2: Delete all chunks from Azure AI Search index
  |   |-> delete_by_document_id() removes all chunk entries
  |-- Step 3: Delete blob from Azure Blob Storage
  |
  v
[Frontend updates]
  |-- Document removed from popover list
  |-- Badge count decremented
  |-- If last document deleted: badge disappears
  |
  v
End
```

**Error Paths**:

- Download fails (blob URL expired) -> "Unable to download. Please try again."
- Delete fails (backend error) -> "Unable to delete document. Please try again." Document remains in list.
- Document stuck in "processing" -> delete still available (cleans up partial data)

---

## 6. Upload Error Recovery

**Trigger**: An error occurs during any stage of the upload pipeline.

### Extraction Failure

```
Start
  |
  v
[Background extraction task fails]
  |-- Corrupt file, unsupported internal format, library error
  |
  v
[Document status set to "failed"]
  |-- Error message stored in document record
  |-- Blob remains in storage (for retry)
  |
  v
[User sees in AttachmentPopover]
  |-- Document shown with "failed" status badge (red)
  |-- Paperclip icon turns red
  |-- Error context: "Processing failed"
  |
  v
[User options]
  |
  +-- Retry: delete and re-upload the file
  |     |-> Delete removes failed document
  |     |-> Re-upload starts fresh pipeline
  |
  +-- Delete: remove the failed document entirely
  |     |-> Cascade cleanup: metadata, any partial index entries, blob
  |
  v
End
```

### Upload Timeout

```
Start
  |
  v
[Upload request exceeds timeout]
  |-- Network slow, large file, server overloaded
  |
  v
[Frontend: getFriendlyErrorMessage() maps error]
  |-- Pattern: "timeout" or "Timeout"
  |-- Message: "Upload timed out. Please try again with a smaller file..."
  |
  v
[Upload state reset]
  |-- isUploading = false
  |-- uploadProgress = null (clears after 3s)
  |-- No document record created (upload did not complete)
  |
  v
[User can retry immediately]
  |-- Drop or select the same file again
  |-- Full pipeline restarts from scratch
  |
  v
End
```

### Network Failure Mid-Upload

```
Start
  |
  v
[Network connection drops during upload]
  |
  v
[Frontend: fetch() rejects with NetworkError]
  |-- getFriendlyErrorMessage() maps:
  |   "NetworkError" or "Failed to fetch"
  |   -> "Network error. Please check your connection..."
  |
  v
[Upload state reset]
  |-- No resume support -- re-upload required
  |-- If conversation was auto-created: it persists (empty but available)
  |
  v
[User restores connection and re-uploads]
  |-- Same file, same flow
  |-- Previous partial blob (if any) overwritten (overwrite=True)
  |
  v
End
```

### Vision Processing Failure

```
Start
  |
  v
[Vision API call fails during analyzing_images stage]
  |-- Timeout, rate limit, API error
  |
  v
[Graceful degradation]
  |-- Document continues processing WITHOUT image descriptions
  |-- Text extraction and chunking proceed normally
  |-- Image chunks omitted from index (no description content)
  |-- Document status still transitions to "ready"
  |
  v
[Document searchable but with reduced context]
  |-- Text content fully indexed and searchable
  |-- Image content not included in search results
  |-- No user-visible error (silent degradation)
  |
  v
End
```

### Rate Limit During Upload

```
Start
  |
  v
[Server returns 429 (rate limit)]
  |
  v
[Frontend: getFriendlyErrorMessage() maps error]
  |-- Pattern: "RateLimitError" or "429"
  |-- Message: "Too many files uploaded at once. Please wait a minute..."
  |
  v
[Upload state reset]
  |
  v
[User waits and retries]
  |-- Rate limit typically resets within 60 seconds
  |-- User re-drops or re-selects the file
  |
  v
End
```

### Quota Exceeded

```
Start
  |
  v
[Server returns quota error during embedding/indexing]
  |
  v
[Frontend: getFriendlyErrorMessage() maps error]
  |-- Pattern: "quota" or "Quota"
  |-- Message: "Service quota exceeded. Please try again later..."
  |
  v
[Document status set to "failed"]
  |-- Blob uploaded but processing incomplete
  |-- User can retry later or delete
  |
  v
End
```

---

## Upload Limits Reference

| Limit                          | Value          | Enforcement                                   |
| ------------------------------ | -------------- | --------------------------------------------- |
| Max file size                  | 30 MB          | Frontend pre-check + backend post-read check  |
| Max documents per conversation | 20             | Backend validate_file()                       |
| Max filename length            | 255 characters | Backend validate_file() + sanitize_filename() |
| Max images per doc (vision)    | Config-driven  | Backend \_process_vision()                    |

## Supported File Types

| Tier | Extensions                           | Category         |
| ---- | ------------------------------------ | ---------------- |
| 1    | pdf, docx, doc, xlsx, xls, pptx, ppt | Office Documents |
| 2    | csv, txt, md                         | Plain Text       |
| 3    | html, htm, json, xml, eml            | Web/Data         |
| 4    | jpg, jpeg, png, bmp, tiff, gif, webp | Images (Vision)  |

---

## Flow Summary

| Flow | Flow Name                  | Trigger                | Primary API                                          | Key Failure Mode                       |
| ---- | -------------------------- | ---------------------- | ---------------------------------------------------- | -------------------------------------- |
| 01   | Drag-and-Drop Upload       | File drag into browser | POST /v1/conversations/{id}/documents (SSE)          | Invalid type, size > 30MB, > 20 docs   |
| 02   | Clipboard Paste Upload     | Ctrl+V / Cmd+V         | Same as Flow 01                                      | Unsupported type, upload in progress   |
| 03   | Mobile/Touch Upload        | Tap file picker        | Same as Flow 01                                      | Timeout on slow connection             |
| 04   | Auto-Conversation Creation | Upload without convo   | POST /conversations/ + Flow 01                       | Orphan conversation on validation fail |
| 05   | Attachment Management      | Click paperclip badge  | GET/DELETE /v1/conversations/{id}/documents/{doc_id} | Blob URL expired, delete cascade fail  |
| 06   | Upload Error Recovery      | Pipeline failure       | Retry via re-upload                                  | Persistent failures, quota exhaustion  |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
