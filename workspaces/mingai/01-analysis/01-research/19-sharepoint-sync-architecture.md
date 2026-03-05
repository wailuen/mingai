# 19. SharePoint Sync Architecture

> **Source**: `aihub2/src/` codebase — API service, sync worker, shared libraries, frontend types
> **Date**: 2026-03-04
> **Status**: Complete
> **Purpose**: Reference architecture for porting SharePoint sync to the multi-tenant mingai platform

---

## 1. OAuth2 Client Credentials Flow

The SharePoint integration authenticates via Azure AD **client credentials grant** (application-level, no interactive user consent). The implementation lives in the shared library so both the API service and sync worker share the same authentication logic.

### Token Acquisition

```
POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id={client_id}
&client_secret={client_secret}
&scope=https://graph.microsoft.com/.default
```

**Source**: `mingai_shared/services/sharepoint_client.py`

The `SharePointClient` class manages the full token lifecycle:

```python
# From sharepoint_client.py - Token URL construction
self._token_url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
self._scope = "https://graph.microsoft.com/.default"
```

### Token Caching and Refresh

Tokens are cached in-memory with a **60-second pre-expiry refresh buffer**. The client checks `_token_expires_at` before every Graph API call and refreshes proactively to avoid mid-request expiration. This is a pure in-memory cache — there is no Redis or persistent token storage.

### Credential Storage

Credentials come from two sources, with env vars taking priority:

| Credential    | Env Var                    | Key Vault Secret           |
| ------------- | -------------------------- | -------------------------- |
| Tenant ID     | `SHAREPOINT_TENANT_ID`     | `sharepoint-tenant-id`     |
| Client ID     | `SHAREPOINT_CLIENT_ID`     | `sharepoint-client-id`     |
| Client Secret | `SHAREPOINT_CLIENT_SECRET` | `sharepoint-client-secret` |

The `SecretManager` class (`app/services/secret_manager.py`) implements this fallback:

1. Check environment variable
2. If not found, query Azure Key Vault via `azure.keyvault.secrets.SecretClient`
3. Cache the resolved value in-memory for the process lifetime

### Rate Limiting and Retry

The Graph API client includes built-in resilience:

- **Token bucket rate limiter**: 10 requests/second default, configurable
- **Exponential backoff retry**: 3 retries with configurable base delay
- **429 handling**: Respects `Retry-After` header from Graph API
- **SSRF protection**: File download redirects are validated against an allowed domain list (`graph.microsoft.com`, `*.sharepoint.com`)

### Multi-Tenant Gap

Credentials are stored at the **application level** (environment variables / single Key Vault). There is no per-tenant credential isolation. The `SharePointClient` constructor takes a single `tenant_id` — it cannot serve multiple Microsoft 365 tenants simultaneously.

---

## 2. Site and Library Browsing API

The browsing API enables admins to navigate their SharePoint environment before creating sync indexes. All endpoints live under `/admin/sharepoint` and require `require_index_or_admin()` role plus `require_sharepoint_enabled` dependency.

### Endpoints

| Endpoint                     | Method | Description                                              |
| ---------------------------- | ------ | -------------------------------------------------------- |
| `/connection/status`         | GET    | Test Graph API connectivity, return tenant name          |
| `/sites`                     | GET    | List accessible sites (excludes OneDrive personal sites) |
| `/sites/{site_id}`           | GET    | Get specific site details                                |
| `/sites/{site_id}/libraries` | GET    | List document libraries (drives) within a site           |
| `/drives/{drive_id}/folders` | GET    | List folders within a library for folder selection       |

**Source**: `app/modules/sharepoint/router.py`

### Input Validation

Every path/query parameter is validated with regex patterns and length limits before reaching the Graph API:

```python
# From router.py - Validation patterns
SITE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9\-,\.]+$')
DRIVE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9\-!_\.]+$')
INDEX_ID_PATTERN = re.compile(r'^idx_sp_[a-f0-9]{12}$')

MAX_ID_LENGTH = 200
MAX_SEARCH_LENGTH = 100
MAX_PATH_LENGTH = 500
```

Search queries are additionally sanitized by stripping `<>"'\\/;` characters to prevent injection into Graph API OData queries.

Folder paths accept three formats: the keyword `"root"`, alphanumeric item IDs, and `/`-prefixed paths (with path traversal `..` explicitly blocked).

### Graph API Calls

The `SharePointClient` methods map to Microsoft Graph endpoints:

- `list_sites(search, skip, top, exclude_onedrive)` → `GET /sites?$search={query}&$top={top}&$skip={skip}`
- `get_site(site_id)` → `GET /sites/{site_id}`
- `list_libraries(site_id)` → `GET /sites/{site_id}/drives` (filtered to `documentLibrary` type)
- `list_folder_contents(drive_id, folder_path)` → `GET /drives/{drive_id}/items/{item_id}/children` or `GET /drives/{drive_id}/root/children`

Results are returned with pagination support (`has_more` flag) and sorted alphabetically by display name.

---

## 3. Index Creation and Deterministic ID Generation

When an admin selects a site, library, and optional folder path, the system creates a **SharePoint index** — a logical entity that tracks what to sync, how to sync, and the current sync state.

### Deterministic Index ID

Index IDs are generated deterministically from the source location triple, ensuring the same SharePoint folder always maps to the same index:

```python
# From index_service.py - _generate_deterministic_index_id()
raw = f"{site_id}|{drive_id}|{normalized_folder_path}"
hash_hex = hashlib.sha256(raw.encode()).hexdigest()[:12]
return f"idx_sp_{hash_hex}"
```

The folder path is normalized (lowered, stripped of trailing slashes, default `"/"`) before hashing. This produces IDs like `idx_sp_a3f2b1c4d5e6` that are:

- Validated on every API call via `INDEX_ID_PATTERN = r'^idx_sp_[a-f0-9]{12}$'`
- Unique per source location (collision probability ~1 in 2.8 trillion)
- Reproducible for idempotent creation

### Uniqueness Check

Before creation, the service checks both storage layers:

1. **CosmosDB**: Query for existing document with the generated `index_id`
2. **Azure AI Search**: Check if a search index with name `mingai-sp-{index_id}` already exists

If either exists, the creation is rejected with a 409 Conflict response.

### Azure AI Search Index Schema

The search index is created with the following field structure, defined in `sharepoint_constants.py`:

```python
# Key fields
INDEX_PREFIX = "mingai-sp-"
EMBEDDING_MODEL = "text-embedding-3-large"
VECTOR_DIMENSIONS = 3072
EMBEDDING_BATCH_SIZE = 16
```

Field categories from `get_sharepoint_index_fields()`:

| Category | Fields                                                         | Purpose                          |
| -------- | -------------------------------------------------------------- | -------------------------------- |
| Core     | `id`, `content`, `title`                                       | Document identification and text |
| Vector   | `content_vector` (3072 dims)                                   | HNSW cosine similarity search    |
| Source   | `source_file`, `source_url`, `file_type`                       | File provenance                  |
| Location | `page_number`, `slide_number`, `sheet_name`, `section_heading` | Chunk location within document   |
| Dedup    | `etag`, `content_hash`                                         | Multi-level deduplication        |
| Vision   | `chunk_type`, `image_type`, `is_image_description`             | Image description chunks         |
| Metadata | `last_modified`, `file_size`, `created_at`                     | Temporal and size metadata       |

The vector search configuration uses **HNSW** (Hierarchical Navigable Small World) with cosine metric and a semantic search configuration layered on top.

### CosmosDB Index Document

The index metadata is stored as a single CosmosDB document with embedded sync state (NoSQL pattern — no joins):

```python
# Simplified document structure from index_service.py create_index()
{
    "id": "idx_sp_a3f2b1c4d5e6",
    "type": "sharepoint_index",
    "name": "Marketing Documents",
    "sharepoint_config": {
        "site_id": "...",
        "drive_id": "...",
        "folder_path": "/Shared Documents/Marketing",
        "sync_frequency": "daily",       # hourly | daily | weekly
        "sync_hour": 2,                  # 0-23 UTC
        "last_delta_token": null          # Set after first sync
    },
    "description_metadata": { ... },
    "sync_history": [],                   # Bounded array, max 10 entries
    "current_checkpoint": null,           # Set during active sync
    "file_status_summary": {
        "recent_successes": [],           # Bounded, max 20
        "recent_skipped": [],
        "recent_failures": [],
        "recent_deletions": []
    },
    "status": "created",                  # created | syncing | synced | error
    "created_at": "2026-03-04T...",
    "updated_at": "2026-03-04T..."
}
```

---

## 4. Sync Worker Architecture

The sync worker is a **standalone Python process** that runs independently from the API service. It polls a Redis queue for sync jobs and processes them sequentially. The architecture uses four coordinating subsystems: queue, distributed lock, checkpoint recovery, and heartbeat.

### Component Overview

```
API Service                          Sync Worker
┌────────────────┐                  ┌─────────────────────┐
│ POST /sync     │──RPUSH──────────>│ BLPOP (1s timeout)  │
│                │                  │                     │
│ GET /progress  │<──GETEX──────────│ ProgressPublisher   │
│ GET /sse       │<──SUBSCRIBE──────│  (SETEX + PUBLISH)  │
│                │                  │                     │
│ POST /cancel   │──SETEX flag─────>│ CheckpointManager   │
│                │                  │ HeartbeatPublisher   │
└────────────────┘                  └─────────────────────┘
         │                                    │
         └──────── Redis ─────────────────────┘
```

**Source**: `sync-worker/app/worker.py`

### Redis Queue

The queue is a Redis list operated by `SyncQueueService` (`app/services/sync_queue.py`):

```python
# Key pattern from RedisKeyBuilder
queue_key = "{prefix}sharepoint:sync:queue"    # Redis LIST
active_key = "{prefix}sharepoint:sync:active"  # Redis SET
```

- **Enqueue**: `RPUSH` for normal priority, `LPUSH` for high priority
- **Dequeue**: Worker uses `BLPOP` with 1-second timeout for responsive shutdown
- **Dedup**: Before enqueue, checks both the active set and existing queue items to prevent duplicate syncs
- **Active tracking**: Index ID added to active set on dequeue, removed on completion

Job payload structure:

```json
{
  "index_id": "idx_sp_a3f2b1c4d5e6",
  "triggered_by": "admin@company.com",
  "sync_type": "incremental",
  "priority": "normal",
  "enqueued_at": "2026-03-04T10:00:00Z"
}
```

### Distributed Lock

The `CheckpointManager` provides a distributed lock to prevent concurrent syncs of the same index across multiple worker instances:

```python
# From checkpoint.py - acquire_sync_lock()
SYNC_LOCK_TTL_MS = 600_000  # 10 minutes

acquired = await redis_client.set(
    key,          # "{prefix}sync_lock:{index_id}"
    lock_value,   # Unique per job (job_id or uuid4)
    nx=True,      # Only set if not exists
    px=SYNC_LOCK_TTL_MS,
)
```

Release uses a **Lua script** for atomic compare-and-delete — ensuring only the lock holder can release:

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

**Fail-open policy**: If Redis is unavailable, the lock acquisition returns `True` — syncs proceed rather than being permanently blocked. This is a deliberate trade-off favoring availability over strict mutual exclusion.

### Worker Main Loop

The `SyncWorker` class implements the processing lifecycle:

```
1. BLPOP job from queue (1s timeout)
2. Parse and validate job JSON
3. Register as running job (Redis HSET)
4. Acquire distributed lock
5. Check for existing checkpoint (crash recovery)
6. If checkpoint exists: resume from last_document_id
7. If no checkpoint: start fresh
8. Execute SyncProcessor.process_job()
9. Push result to sync history (CosmosDB + Redis)
10. Release distributed lock
11. Clear checkpoint
12. Unregister running job
```

On graceful shutdown (SIGTERM/SIGINT), the worker:

- Saves current checkpoint to Redis
- Unregisters running job
- Closes Redis connections
- Publishes final heartbeat with "stopping" status

### Heartbeat

The `HeartbeatPublisher` (`sync-worker/app/heartbeat.py`) provides worker liveness detection:

```python
DEFAULT_HEARTBEAT_INTERVAL = 10  # seconds
HEARTBEAT_TTL_SECONDS = 30       # auto-expire if worker dies
```

Worker ID format: `{hostname}-{uuid4[:8]}` (e.g., `sync-worker-0-a1b2c3d4`)

Heartbeat payload published every 10 seconds:

```json
{
  "worker_id": "sync-worker-0-a1b2c3d4",
  "container_id": "abc123",
  "status": "processing",
  "last_heartbeat": "2026-03-04T10:00:10Z",
  "started_at": "2026-03-04T09:00:00Z",
  "current_job_id": "idx_sp_a3f2b1c4d5e6",
  "jobs_completed": 42,
  "jobs_failed": 1,
  "memory_usage_mb": 256.5
}
```

Dual publish: `SETEX` to heartbeat key (for polling) + `PUBLISH` to status channel (for real-time monitoring).

If no heartbeat is received within the 30-second TTL, the key auto-expires, allowing monitoring systems to detect dead workers.

---

## 5. Delta Sync with Microsoft Graph Delta Queries

The sync system uses Microsoft Graph **delta queries** for incremental synchronization — only fetching changes since the last sync rather than re-listing the entire library.

### Delta Token Lifecycle

```
First Sync (No Delta Token)
    └─> GET /drives/{drive_id}/root/delta
        └─> Process ALL files
        └─> Store @odata.deltaLink token
            └─> Saved to sharepoint_config.last_delta_token in CosmosDB

Subsequent Sync (Has Delta Token)
    └─> GET {stored_delta_link}
        └─> Returns ONLY changed/added/deleted files
        └─> Store new @odata.deltaLink token

Delta Token Expired (410 Gone)
    └─> DeltaTokenExpiredError caught
    └─> Fallback to full sync (no delta token)
    └─> Store new delta token after completion
```

**Source**: `mingai_shared/services/sharepoint_client.py` — `get_delta_changes()` method

### Folder Scoping

When an index targets a specific subfolder (not the drive root), delta queries are scoped:

- Root folder: `GET /drives/{drive_id}/root/delta`
- Subfolder: First resolves the folder's Graph item ID via `resolve_folder_path()`, then queries `GET /drives/{drive_id}/items/{folder_item_id}/delta`

### Change Types

The delta response includes `@removed` annotations and modification timestamps. The sync processor categorizes each item:

| Delta Signal                 | Action                                     |
| ---------------------------- | ------------------------------------------ |
| New file (not in index)      | Download, process, embed, index            |
| Modified file (eTag changed) | Dedup check, re-process if content changed |
| Deleted file (`@removed`)    | Remove all chunks from Azure Search        |
| Folder (ignored)             | Skip — only files are processed            |

### Sync Types

The system supports two sync modes, controlled by the job payload:

- **Full sync**: Ignores delta token, lists all files from scratch. Used for first sync, reset, or delta token expiry.
- **Incremental sync**: Uses stored delta token. Used for scheduled syncs and manual re-syncs after the first sync.

---

## 6. File Processing Pipeline

The file processing pipeline transforms raw SharePoint documents into searchable, embedded chunks in Azure AI Search. This is the core value-creation step.

### Pipeline Stages

```
SharePoint Graph API
    │
    ▼
[1] Download File (streaming, temp file)
    │
    ▼
[2] Deduplication Check
    │  ├─ eTag match → Skip (no change)
    │  ├─ eTag differs, hash match → Update metadata only
    │  └─ Content changed → Continue to extraction
    │
    ▼
[3] Text Extraction (format-specific)
    │  ├─ PDF: PyPDF2 / pdfplumber
    │  ├─ DOCX: python-docx
    │  ├─ XLSX: openpyxl
    │  ├─ PPTX: python-pptx
    │  ├─ CSV/TXT/MD: direct read
    │  └─ HTML/JSON/XML/EML: format parsers
    │
    ▼
[4] Vision Processing (optional)
    │  ├─ Embedded images in PDF/DOCX/PPTX
    │  └─ Standalone images (JPG/PNG/etc.)
    │  └─ GPT-vision generates text descriptions
    │
    ▼
[5] Chunking (token-based)
    │  ├─ Max tokens: 1000 per chunk
    │  ├─ Overlap: 100 tokens
    │  ├─ Tokenizer: tiktoken cl100k_base
    │  └─ Location metadata preserved (page, slide, sheet, section)
    │
    ▼
[6] Embedding Generation
    │  ├─ Model: text-embedding-3-large
    │  ├─ Dimensions: 3072
    │  ├─ Batch size: 16 chunks
    │  └─ Azure OpenAI endpoint
    │
    ▼
[7] Index to Azure AI Search
       ├─ Merge-or-upload action
       ├─ Each chunk is a document with content_vector
       └─ Dedup fields (etag, content_hash) stored per chunk
```

### Deduplication (Two-Level)

The `FileDeduplicator` (`app/modules/sharepoint/deduplicator.py`) implements multi-level dedup to minimize unnecessary re-processing:

**Level 1 — eTag comparison** (fast, no download):

- Query Azure Search for existing chunks with the same source file
- Compare the stored `etag` against the current file's eTag from Graph API
- If match: file is unchanged, skip entirely

**Level 2 — SHA-256 content hash** (accurate, requires download):

- Triggered when eTag differs (common after metadata-only changes like permission updates)
- Compute SHA-256 hash of the downloaded file content
- Compare against stored `content_hash`
- If match: only metadata changed — update eTag field without re-embedding
- If differs: content truly changed — full re-processing

### Chunk Document Schema

Each chunk uploaded to Azure AI Search:

```json
{
    "id": "{index_id}_{file_id}_{chunk_index}",
    "content": "The quarterly report shows...",
    "content_vector": [0.023, -0.041, ...],  // 3072 floats
    "title": "Q4-Report.pdf",
    "source_file": "Q4-Report.pdf",
    "source_url": "https://company.sharepoint.com/...",
    "file_type": "pdf",
    "page_number": 3,
    "slide_number": null,
    "sheet_name": null,
    "section_heading": "Financial Summary",
    "etag": "\"abc123\"",
    "content_hash": "sha256:a1b2c3...",
    "chunk_type": "text",
    "image_type": null,
    "is_image_description": false,
    "last_modified": "2026-03-01T...",
    "file_size": 1048576,
    "created_at": "2026-03-04T..."
}
```

### Error Budget

The sync processor has a hard limit on consecutive errors:

```python
MAX_ERRORS_BEFORE_ABORT = 10
```

If 10 files fail consecutively during a single sync, the entire sync is aborted to prevent cascading failures. Individual file errors are tracked in the `file_status_summary.recent_failures` array (bounded to 20 entries).

---

## 7. Supported File Types

File type support is tiered by extraction complexity and processing requirements.

### Tier Classification

| Tier                        | Extensions                                                | Extraction Method          | Notes                                                  |
| --------------------------- | --------------------------------------------------------- | -------------------------- | ------------------------------------------------------ |
| **Tier 1** (Rich Documents) | `.pdf`, `.docx`, `.xlsx`, `.pptx`                         | Dedicated parsers          | Full structure preservation, page/slide/sheet metadata |
| **Tier 2** (Plain Text)     | `.csv`, `.txt`, `.md`                                     | Direct read / simple parse | Minimal processing overhead                            |
| **Tier 3** (Structured)     | `.html`, `.json`, `.xml`, `.eml`                          | Format-specific parsers    | HTML tag stripping, JSON flattening, email extraction  |
| **Tier 4** (Images)         | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.gif`, `.webp` | GPT-vision                 | Standalone images processed as image descriptions      |

**Source**: `sync-worker/app/services/sync_processor.py`

### Vision Processing

Vision-capable file types get additional processing:

- **VISION_SUPPORTED_EXTENSIONS**: `.pdf`, `.pptx`, `.docx` — embedded images are extracted and described
- **STANDALONE_IMAGE_EXTENSIONS**: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.gif`, `.webp` — entire file is an image

Vision-generated chunks are tagged with:

- `chunk_type = "image_description"`
- `image_type` = format identifier (e.g., `"png"`, `"jpeg"`)
- `is_image_description = true`

This allows the RAG query pipeline to distinguish text-extracted chunks from vision-generated descriptions, enabling different ranking or filtering strategies.

### Chunking Parameters

Defined in `DocumentProcessor` (`mingai_shared/services/document_processor.py`):

```python
DEFAULT_MAX_TOKENS = 1000
OVERLAP_TOKENS = 100
# Tokenizer: tiktoken with cl100k_base encoding
```

Each `DocumentChunk` carries location metadata:

- `page_number`: PDF pages, Word pages
- `slide_number`: PowerPoint slides
- `sheet_name`: Excel worksheet names
- `section_heading`: Detected heading from document structure

---

## 8. Progress Tracking and SSE Streaming

The progress system provides real-time sync visibility to the admin UI through a **dual-channel Redis architecture**: polling-based for on-demand status checks, and pub/sub for live streaming.

### Dual Redis Channels

**Source**: `sync-worker/app/progress.py` (publisher) and `app/modules/sharepoint/progress_tracker.py` (consumer)

```python
# From RedisKeyBuilder — two keys per index sync
progress_key = "{prefix}sync_progress:{index_id}"    # SETEX, 1h TTL
channel_key = "{prefix}sync_channel:{index_id}"       # PUBLISH (pub/sub)
```

**Channel 1 — Polling (SETEX)**:

- Progress data stored as JSON with 1-hour TTL
- API endpoint `GET /indexes/{index_id}/sync/progress` reads this key
- Used for page-load state recovery (SSE may not be connected yet)
- Falls back to CosmosDB checkpoint, then sync_history if Redis key expired

**Channel 2 — Streaming (PUBLISH/SUBSCRIBE)**:

- Real-time events published to `sync_channel:{index_id}`
- API endpoint `GET /indexes/{index_id}/sync/sse` subscribes to this channel
- SSE stream with 15-second keepalive heartbeats
- Auto-closes on terminal events: `sync_complete`, `sync_error`, `sync_cancelled`

### Progress Message Format

The `ProgressPublisher` emits structured events consumed by the frontend:

```python
# From progress.py - ProgressMessage structure
{
    "event_type": "sync_progress",       # sync_started | sync_progress | sync_complete | sync_error | sync_cancelled
    "index_id": "idx_sp_a3f2b1c4d5e6",
    "total_files": 150,
    "processed_files": 42,
    "failed_files": 1,
    "skipped_files": 5,
    "current_file": "Q4-Report.pdf",
    "phase": "processing",               # discovery | processing | finalizing
    "started_at": "2026-03-04T10:00:00Z",
    "updated_at": "2026-03-04T10:05:30Z"
}
```

### SSE Implementation (API Side)

The SSE endpoint (`sync_endpoints.py`) implements the streaming protocol:

```python
# Simplified from sync_endpoints.py GET /indexes/{index_id}/sync/sse
async def sync_sse_stream(index_id: str):
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_key)

    try:
        while True:
            message = await pubsub.get_message(timeout=15.0)
            if message and message["type"] == "message":
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                if event_type in ("sync_complete", "sync_error", "sync_cancelled"):
                    break
            else:
                yield f": keepalive\n\n"  # 15s heartbeat
    finally:
        await pubsub.unsubscribe(channel_key)
```

### Frontend Type Mapping

The frontend TypeScript types (`src/types/sharepoint.ts`) define a discriminated union for file status and SSE progress:

```typescript
// From sharepoint.ts
interface SseSyncProgress {
  event_type:
    | "sync_started"
    | "sync_progress"
    | "sync_complete"
    | "sync_error"
    | "sync_cancelled";
  index_id: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  skipped_files: number;
  current_file: string | null;
  phase: "discovery" | "processing" | "finalizing";
}
```

### Cancellation Flow

Cancellation is cooperative, using a Redis flag:

```
Admin clicks "Cancel"
    └─> POST /indexes/{index_id}/sync/cancel
        └─> SETEX "sync_cancel:{index_id}" = "1" (TTL: 1h)

Sync Worker (in processing loop)
    └─> Before each file: GET "sync_cancel:{index_id}"
        └─> If set: save checkpoint, publish sync_cancelled event, stop
```

The checkpoint is preserved on cancellation so the next sync can resume from where it stopped (unless the admin explicitly resets via `POST /indexes/{index_id}/sync/reset`).

---

## 9. Multi-Tenant Gap Analysis

The current architecture is **single-tenant by design**. Converting to multi-tenant requires changes at every layer of the SharePoint integration stack.

### Current Single-Tenant Assumptions

| Layer                    | Current Implementation                      | Multi-Tenant Requirement                                          |
| ------------------------ | ------------------------------------------- | ----------------------------------------------------------------- |
| **OAuth Credentials**    | Single set of env vars / Key Vault secrets  | Per-tenant Azure AD app registration or admin consent             |
| **SharePoint Client**    | One `SharePointClient` instance per process | Tenant-scoped client pool or factory                              |
| **Graph API Scope**      | `https://graph.microsoft.com/.default`      | Same scope, but per-tenant token endpoint                         |
| **Redis Keys**           | Prefix `mingai:` — no tenant isolation      | Prefix `mingai:{tenant_id}:` — namespaced per tenant              |
| **Azure Search Indexes** | Naming: `mingai-sp-{index_id}`               | Naming: `{tenant_id}-sp-{index_id}` or dedicated index per tenant |
| **CosmosDB Documents**   | No tenant_id field                          | Partition key should include tenant_id                            |
| **Worker Queue**         | Single queue for all syncs                  | Per-tenant queue or tenant-tagged jobs                            |
| **Scheduled Sync**       | APScheduler in API container                | Per-tenant schedule evaluation                                    |

### Required Changes by Component

**1. OAuth Consent and Credential Vault**

Each tenant's Microsoft 365 organization must grant consent to the mingai application. Two approaches:

- **Multi-tenant Azure AD App**: Register the app as multi-tenant in Azure AD. Each tenant admin grants admin consent. Token requests use the tenant's specific `tenant_id` in the token URL. The `client_id` and `client_secret` remain the same (app-level), but the `tenant_id` varies per request.
- **Per-Tenant App Registration**: Each tenant provisions their own Azure AD app registration, providing their own `client_id` and `client_secret`. More isolated but higher operational overhead.

Credentials must be stored per-tenant in a vault with tenant isolation (e.g., Key Vault with tenant-prefixed secret names, or a dedicated secrets table with tenant_id column).

**2. SharePoint Client Factory**

Replace the singleton `get_sharepoint_client()` with a factory that creates tenant-scoped clients:

```python
# Current (single-tenant)
client = get_sharepoint_client()

# Required (multi-tenant)
client = get_sharepoint_client(tenant_id=request_tenant_id)
# Internally: resolve credentials for this tenant, create or cache client
```

A client pool with LRU eviction would prevent unbounded memory growth while avoiding repeated token acquisition for active tenants.

**3. Redis Key Namespace**

The `RedisKeyBuilder` currently uses a flat `mingai:` prefix. Multi-tenant requires tenant isolation:

```python
# Current
"mingai:sharepoint:sync:queue"
"mingai:sync_progress:idx_sp_abc123"

# Required
"mingai:{tenant_id}:sharepoint:sync:queue"
"mingai:{tenant_id}:sync_progress:idx_sp_abc123"
```

This prevents cross-tenant data leakage in Redis and allows per-tenant queue prioritization.

**4. Azure AI Search Isolation**

Three strategies, each with trade-offs:

| Strategy                     | Isolation            | Cost    | Complexity                                               |
| ---------------------------- | -------------------- | ------- | -------------------------------------------------------- |
| Shared index + tenant filter | Low (software fence) | Lowest  | Add `tenant_id` to every document, filter on every query |
| Index-per-tenant             | High (index-level)   | Medium  | Create `{tenant_id}-sp-{index_id}` indexes               |
| Service-per-tenant           | Maximum              | Highest | Dedicated Azure Search service per tenant                |

The current index naming (`mingai-sp-{index_id}`) and schema would need a `tenant_id` field at minimum, regardless of isolation strategy.

**5. Worker Queue Architecture**

Two options for multi-tenant job processing:

- **Single queue with tenant tags**: Jobs include `tenant_id` in the payload. Workers process all tenants. Simple but no tenant-level priority or rate limiting.
- **Per-tenant queues**: Separate Redis list per tenant (`mingai:{tenant_id}:sync:queue`). Workers round-robin across tenant queues. Enables per-tenant fairness and rate limiting.

**6. Sync Schedule**

The current `SharePointSyncJob` iterates all indexes in a single APScheduler job. Multi-tenant requires:

- Partition schedule evaluation by tenant
- Respect per-tenant rate limits
- Prevent one tenant's large library from starving others

### Migration Priority (Recommended Order)

1. **Redis key namespacing** — Low risk, high impact. Prevents cross-tenant leakage from day one.
2. **CosmosDB tenant_id** — Add tenant_id as partition key component. Required for data isolation.
3. **SharePoint client factory** — Replace singleton with tenant-scoped factory.
4. **Per-tenant credential storage** — Vault design for tenant OAuth credentials.
5. **Azure Search isolation** — Start with shared index + filter, migrate to per-tenant indexes as needed.
6. **Queue architecture** — Start with tenant-tagged single queue, evolve to per-tenant queues under load.

---

## Appendix: Key File Reference

| File               | Path (relative to `aihub2/src/`)                                 | Purpose                                                |
| ------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ |
| SharePoint Client  | `backend/shared/mingai_shared/services/sharepoint_client.py`      | Graph API client, OAuth2, token caching, rate limiting |
| Constants          | `backend/shared/mingai_shared/services/sharepoint_constants.py`   | Index schema, embedding config, field definitions      |
| Router             | `backend/api-service/app/modules/sharepoint/router.py`           | Input validation, browsing endpoints                   |
| Schemas            | `backend/api-service/app/modules/sharepoint/schemas.py`          | Pydantic models for all SharePoint entities            |
| Index Endpoints    | `backend/api-service/app/modules/sharepoint/index_endpoints.py`  | Index CRUD + description management                    |
| Sync Endpoints     | `backend/api-service/app/modules/sharepoint/sync_endpoints.py`   | Sync trigger, progress, SSE, cancel, reset             |
| Index Service      | `backend/api-service/app/modules/sharepoint/index_service.py`    | Core service with mixin pattern                        |
| Progress Tracker   | `backend/api-service/app/modules/sharepoint/progress_tracker.py` | Redis progress + CosmosDB fallback                     |
| Deduplicator       | `backend/api-service/app/modules/sharepoint/deduplicator.py`     | Two-level file deduplication                           |
| Sync Queue         | `backend/api-service/app/services/sync_queue.py`                 | Redis queue with priority                              |
| Scheduled Job      | `backend/api-service/app/jobs/sharepoint_sync_job.py`            | APScheduler sync scheduling                            |
| Secret Manager     | `backend/api-service/app/services/secret_manager.py`             | Key Vault + env var fallback                           |
| Worker             | `sync-worker/app/worker.py`                                      | Main worker loop, job lifecycle                        |
| Config             | `sync-worker/app/config.py`                                      | Worker settings                                        |
| Progress           | `sync-worker/app/progress.py`                                    | Dual Redis progress publisher                          |
| Sync Processor     | `sync-worker/app/services/sync_processor.py`                     | Core processing: delta, extract, embed, index          |
| Checkpoint         | `sync-worker/app/checkpoint.py`                                  | Checkpoint + distributed lock                          |
| Heartbeat          | `sync-worker/app/heartbeat.py`                                   | Worker liveness detection                              |
| Redis Utils        | `backend/shared/mingai_shared/redis/utils.py`                     | Key builder, Redis client factory                      |
| Document Processor | `backend/shared/mingai_shared/services/document_processor.py`     | Text extraction, chunking                              |
| Frontend Types     | `frontend/src/types/sharepoint.ts`                               | TypeScript type definitions                            |
