# 22. Google Drive Sync Architecture

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Reference architecture for Google Drive integration as the second cloud storage connector, parallel to SharePoint (`19-sharepoint-sync-architecture.md`).
> **Scope**: Authentication, folder browsing, sync worker, multi-tenant isolation, supported file types, and comparison with SharePoint.

---

## 1. Authentication Strategy

### Two Auth Modes

Google Drive integration supports two authentication modes depending on the customer's Google setup:

| Mode                                         | Who it's for                                           | How it works                                                                                                                                                |
| -------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Service Account + Domain-Wide Delegation** | Google Workspace customers (business/enterprise Gmail) | Platform registers a Google Cloud service account. Workspace admin grants domain-wide delegation. Service account impersonates users to access their Drive. |
| **OAuth 2.0 User Consent**                   | Non-Workspace Google accounts (personal, education)    | Each tenant admin completes an OAuth 2.0 consent flow granting read access to specific folders/drives.                                                      |

**Recommended default**: Service Account + Domain-Wide Delegation for enterprise tenants (mirrors SharePoint application-level auth). OAuth 2.0 as fallback for non-Workspace setups.

### Service Account Authentication Flow

```
1. Platform admin creates GCP Project → creates Service Account → downloads JSON key
2. Workspace admin grants domain-wide delegation to the service account for scopes:
     https://www.googleapis.com/auth/drive.readonly
     https://www.googleapis.com/auth/drive.metadata.readonly
3. Tenant admin provides their Google Workspace domain and the folder(s) to sync
4. Sync worker impersonates a service account to access tenant's Drive:
     credentials = service_account.Credentials.from_service_account_info(
         sa_key_json,
         scopes=["https://www.googleapis.com/auth/drive.readonly"],
         subject="sync-service@tenant-domain.com"  # impersonate sync service user
     )
```

### OAuth 2.0 Consent Flow (non-Workspace)

```
1. Tenant admin clicks "Connect Google Drive"
2. Frontend redirects to Google OAuth consent screen:
     https://accounts.google.com/o/oauth2/v2/auth
     ?client_id={platform_client_id}
     &redirect_uri={api}/integrations/google-drive/callback
     &response_type=code
     &scope=https://www.googleapis.com/auth/drive.readonly
     &access_type=offline
     &prompt=consent
     &state={tenant_id_signed_jwt}
3. User grants access; Google redirects to callback with authorization code
4. Backend exchanges code for access_token + refresh_token
5. Tokens stored in vault, scoped to tenant
```

### Credential Storage (Multi-Tenant)

| Credential               | Storage                                      | Key Pattern                                           |
| ------------------------ | -------------------------------------------- | ----------------------------------------------------- |
| Service Account JSON key | Vault (per-tenant secret)                    | `{vault_path}/{tenant_id}/google-drive/sa-key`        |
| OAuth access_token       | Vault (short-lived, refreshed automatically) | `{vault_path}/{tenant_id}/google-drive/access-token`  |
| OAuth refresh_token      | Vault (long-lived)                           | `{vault_path}/{tenant_id}/google-drive/refresh-token` |
| Configured folder IDs    | PostgreSQL `tenant_integrations` table       | `google_drive_config.folder_ids`                      |

**Critical difference from SharePoint**: SharePoint used a single application-level credential from `.env`. For multi-tenant Google Drive, each tenant's credentials are isolated in vault using the same pattern as the BYOLLM credential vault (`24-platform-rbac-specification.md`).

---

## 2. Google Drive API v3 Endpoints Used

### Connection Status

```
GET https://www.googleapis.com/drive/v3/about?fields=user,storageQuota
```

Returns user info to verify authentication. Equivalent to SharePoint's `/connection/status` endpoint.

### Shared Drive Browsing

```
GET https://www.googleapis.com/drive/v3/drives
```

Lists all Shared Drives the service account can access. Equivalent to SharePoint's `/sites` listing.

### Folder Browsing

```
GET https://www.googleapis.com/drive/v3/files
  ?q=mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false
  &fields=files(id,name,parents,modifiedTime,owners)
  &pageSize=100
  &pageToken={page_token}
```

Paginates through folders. Equivalent to SharePoint's library listing.

### File Listing (within a folder)

```
GET https://www.googleapis.com/drive/v3/files
  ?q='{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'
  &fields=files(id,name,mimeType,size,modifiedTime,md5Checksum,parents,owners,lastModifyingUser)
  &pageSize=1000
  &pageToken={page_token}
```

### File Download / Export

Google-native formats (Docs, Sheets, Slides) must be exported; uploaded files are downloaded directly:

| Source MIME Type                                  | Export MIME Type                                                            | File Extension      |
| ------------------------------------------------- | --------------------------------------------------------------------------- | ------------------- |
| `application/vnd.google-apps.document`            | `application/vnd.openxmlformats-officedocument.wordprocessingml.document`   | `.docx`             |
| `application/vnd.google-apps.spreadsheet`         | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`         | `.xlsx`             |
| `application/vnd.google-apps.presentation`        | `application/vnd.openxmlformats-officedocument.presentationml.presentation` | `.pptx`             |
| `application/pdf`                                 | (direct download)                                                           | `.pdf`              |
| `text/plain`                                      | (direct download)                                                           | `.txt`              |
| `application/vnd.openxmlformats-officedocument.*` | (direct download)                                                           | `.docx/.xlsx/.pptx` |

Export endpoint:

```
GET https://www.googleapis.com/drive/v3/files/{file_id}/export
  ?mimeType={export_mime_type}
```

Direct download:

```
GET https://www.googleapis.com/drive/v3/files/{file_id}?alt=media
```

### Change Tracking (Incremental Sync)

Google Drive uses a `startPageToken` + `changes.list` pattern for incremental sync:

```python
# Initial sync: get the current changes token
token_response = service.changes().getStartPageToken().execute()
start_page_token = token_response["startPageToken"]

# After initial sync, store start_page_token in tenant_integrations table

# Subsequent syncs: fetch only changes since last token
changes_response = service.changes().list(
    pageToken=saved_page_token,
    spaces="drive",
    fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,modifiedTime,parents,trashed))"
).execute()

# IMPORTANT: Pagination must complete BEFORE saving the baseline token.
# - nextPageToken: there are more pages to fetch (pagination cursor only, do NOT save to DB)
# - newStartPageToken: only present on the FINAL page; this is the new sync baseline
# Saving nextPageToken as the baseline would skip subsequent pages on the next sync.

all_changes = []
response = changes_response

while True:
    all_changes.extend(response.get("changes", []))
    next_page = response.get("nextPageToken")
    if not next_page:
        break
    response = service.changes().list(pageToken=next_page, ...).execute()

new_baseline_token = response.get("newStartPageToken")  # only present on final page

# Process all changes atomically THEN save new baseline
async with db.transaction():
    for change in all_changes:
        if change.get("removed") or change.get("file", {}).get("trashed"):
            await delete_from_index(change["fileId"])
        else:
            await upsert_to_index(change["file"])

    # Save new token only after all changes successfully processed
    await integration_state.update(tenant_id, page_token=new_baseline_token)
```

**Comparison with SharePoint**: SharePoint used `deltaLink` from Microsoft Graph for incremental sync. Google uses `changes.list` with `pageToken`. Both patterns are equivalent — track a cursor position, fetch only deltas.

### Push Notifications (Webhook)

Google Drive supports push notifications when files change:

```python
channel = service.files().watch(
    fileId="root",  # or specific folder_id
    body={
        "id": str(uuid4()),            # unique channel ID
        "type": "web_hook",
        "address": "https://api.mingai.com/api/v1/integrations/google-drive/webhook",
        "token": signed_jwt_for_tenant,   # security token
        "expiration": epoch_ms_72h_from_now,  # channels expire, must renew
    }
).execute()
```

**Webhook security**: The `token` field is a signed JWT containing `tenant_id`. Backend verifies the JWT on receipt to prevent forged webhook calls. Google also sends a `X-Goog-Channel-Token` header.

**Channel expiration**: Watch channels expire (max 7 days for Drive). A dedicated `WebhookRenewalJob` runs every 24 hours, queries all integrations with `webhook_expires_at < NOW() + 48h`, and renews those channels. If renewal fails, `webhook_renewal_status` is set to `renewal_failed`, an alert is sent to the platform admin, and the sync falls back to scheduled polling. The channel state fields (`webhook_channel_id`, `webhook_expires_at`, `webhook_renewal_status`) in the data model are essential for this proactive renewal logic.

---

## 3. Sync Worker Design

### Parallel to SharePoint Sync Worker

The Google Drive sync worker mirrors the SharePoint sync worker pattern:

```
[Scheduler: APScheduler]
  |-- per-tenant job: google_drive_sync_{tenant_id}
  |-- cron schedule: configurable per tenant (default: every 6 hours)
  |
  v
[GoogleDriveSyncWorker]
  |
  +-- 1. Load tenant integration config from PostgreSQL
  |       (vault_key_path, folder_ids, last_page_token, sync_mode)
  |
  +-- 2. Retrieve credentials from vault
  |       (service account key or OAuth refresh token)
  |
  +-- 3. Authenticate Google Drive API client
  |
  +-- 4. Determine sync mode:
  |       - FULL: list all files in configured folders
  |       - INCREMENTAL: fetch changes since last_page_token
  |
  +-- 5. For each file to process:
  |       a. Download / export file content
  |       b. Extract text (PDF parser, docx extractor, xlsx→CSV)
  |       c. Chunk text (same chunker as SharePoint: 512 tokens, 50 overlap)
  |       d. Generate embeddings (text-embedding-3-large)
  |       e. Upsert to tenant search index
  |       f. Update sync_status record
  |
  +-- 6. Save new page_token to PostgreSQL
  |
  +-- 7. Emit sync_complete event → NotificationService
```

### Sync Configuration Data Model

```python
# PostgreSQL: tenant_integrations table (new columns or new row type)
{
    "id": "integration-uuid",
    "tenant_id": "tenant-uuid",
    "type": "google_drive",
    "status": "active",            # active | paused | error
    "config": {
        "auth_mode": "service_account",  # service_account | oauth2
        "workspace_domain": "acmecorp.com",
        "folder_ids": [
            {
                "id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs",
                "name": "HR Policies",
                "path": "My Drive / HR / Policies",
                "include_subfolders": True,
            }
        ],
        "sync_schedule": "0 */6 * * *",  # cron expression
        "file_type_filter": ["pdf", "docx", "xlsx", "pptx", "txt"],
        "max_file_size_mb": 100,
    },
    "state": {
        "last_sync_at": "2026-03-05T00:00:00Z",
        "last_page_token": "7622...",       # baseline token (newStartPageToken), saved after full sync
        "total_files_indexed": 1247,
        "last_sync_status": "success",
        "last_error": None,
        "webhook_channel_id": "chan-uuid",   # Google Drive watch channel ID
        "webhook_expires_at": "2026-03-12T00:00:00Z",  # channels expire every 7 days
        "webhook_renewal_status": "active",  # active | expiring_soon | expired | renewal_failed
    },
    "vault_key": "google-drive/sa-key",  # path in vault
    "search_index_id": "index-uuid",     # linked search index
    "created_at": "2026-03-05T00:00:00Z",
    "updated_at": "2026-03-05T00:00:00Z",
}
```

---

## 4. Admin UI for Tenant Setup

### Step 1: Integration Setup Screen

```
[Connect Google Drive]

Authentication Method:
  (•) Google Workspace (Service Account + Domain-Wide Delegation)
  ( ) Personal / Non-Workspace (OAuth 2.0)

Google Workspace Domain: [acmecorp.com       ]

⚠ Before uploading the key:
  1. Create a dedicated Workspace user: mingai-sync@acmecorp.com
     (This must be a real Workspace user, NOT a service account email)
  2. In Google Admin: Security > API Controls > Domain-Wide Delegation
     Add your service account Client ID with scopes:
       drive.readonly, drive.metadata.readonly
  3. Grant this sync user read access to the folders you want to sync

Sync Service User Email: [mingai-sync@acmecorp.com ]
  ↑ This Workspace user will be impersonated during sync (must exist in your directory)

Service Account Key: [Upload JSON key file]
  ⚠ Keep the JSON key secure — treat it like a password.
     The file will be encrypted and stored in the platform's secret vault.

[Validate Connection]  →  ✓ Connected to Google Workspace (acmecorp.com)
                          Impersonating: mingai-sync@acmecorp.com
                          Accessible Shared Drives: 3 found
```

### Step 2: Folder Selection

```
Select Folders to Sync:

📁 Shared Drives
  ├── [✓] Company Policies        (est. 234 files)
  │     └── [✓] Include subfolders
  ├── [ ] Finance Reports
  └── [ ] Engineering Docs

📁 My Drive
  └── [ ] HR Documents

[+ Add Folder by URL or ID]
```

### Step 3: Sync Schedule

```
Sync Schedule:
  ( ) Every hour
  (•) Every 6 hours  (recommended)
  ( ) Every 24 hours
  ( ) Custom cron: [____________]

File Types to Include:
  [✓] PDF    [✓] Word (.docx)  [✓] Excel (.xlsx)
  [✓] PowerPoint (.pptx)  [✓] Text (.txt)
  [ ] Google Docs (auto-exported)   [ ] Google Sheets (auto-exported)

Max File Size: [100] MB

[Save and Start First Sync]
```

---

## 5. Comparison: Google Drive vs SharePoint

| Dimension                     | SharePoint (mingai)                                               | Google Drive (mingai)                                           |
| ----------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------- |
| **Auth**                      | Azure AD client credentials (app-level)                           | Service account + domain-wide delegation OR OAuth 2.0           |
| **API**                       | Microsoft Graph API (REST)                                        | Google Drive API v3 (REST)                                      |
| **Folder hierarchy**          | Sites → Libraries → Folders                                       | Shared Drives → Folders / My Drive → Folders                    |
| **Incremental sync**          | Delta link from Graph API                                         | `changes.list` with `pageToken`                                 |
| **File change notifications** | Microsoft Graph webhooks (subscriptions, 3-day expiry)            | Google Drive watch channels (7-day expiry)                      |
| **Native format handling**    | Office files (direct download)                                    | Google Docs/Sheets/Slides (export required)                     |
| **Access control**            | Site-level and library-level permissions                          | Drive-level and folder-level permissions                        |
| **Multi-tenant isolation**    | Single app credential → does NOT support multiple MS365 tenants   | Per-tenant service account key in vault → natively multi-tenant |
| **Rate limits**               | Graph API: 10,000 req/10min per app                               | Drive API: 1,000 req/100sec per user; 10 req/sec per user       |
| **Search index type**         | Azure AI Search (migrating to OpenSearch per cloud-agnostic plan) | Same — tenant search index (OpenSearch / Azure AI Search)       |
| **Supported file types**      | PDF, Office, TXT                                                  | PDF, Office, TXT, Google Docs/Sheets/Slides (exported)          |

---

## 6. Multi-Tenant Isolation Architecture

Unlike the mingai SharePoint implementation (single-credential, no multi-tenant support), the mingai Google Drive connector is designed multi-tenant from day one:

```
Platform Vault
├── tenant-uuid-A/
│   └── google-drive/
│       ├── sa-key         (Service Account JSON)
│       └── refresh-token  (if OAuth mode)
├── tenant-uuid-B/
│   └── google-drive/
│       └── sa-key
└── tenant-uuid-C/
    └── google-drive/
        └── refresh-token
```

The sync worker loads credentials per-tenant using the `GoogleDriveCredentialResolver`:

```python
class GoogleDriveCredentialResolver:
    async def get_credentials(self, tenant_id: str, auth_mode: str) -> Credentials:
        if auth_mode == "service_account":
            sa_key_json = await vault.get(f"{tenant_id}/google-drive/sa-key")
            # IMPORTANT: domain-wide delegation (DWD) requires `subject` to be a REAL
            # Google Workspace user account email — not a service account email address.
            # The tenant admin must create a dedicated sync service user (e.g.,
            # mingai-sync@acmecorp.com) in their Google Workspace directory, and that
            # user's email is stored in the integration config. Service account emails
            # are NOT valid DWD subjects and will fail with a 401.
            sync_user_email = await integration_config.get(tenant_id, "google_drive_sync_user")
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(sa_key_json),
                scopes=DRIVE_READONLY_SCOPES,
                subject=sync_user_email,  # must be a Workspace user, NOT the SA email
            )
        else:
            refresh_token = await vault.get(f"{tenant_id}/google-drive/refresh-token")
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=PLATFORM_OAUTH_CLIENT_ID,
                client_secret=PLATFORM_OAUTH_CLIENT_SECRET,
            )
        return credentials
```

---

## 7. Rate Limiting and Resilience

Google Drive API quotas are per-project (platform-wide) and per-user:

| Quota                            | Limit                 | Mitigation                                            |
| -------------------------------- | --------------------- | ----------------------------------------------------- |
| Queries per 100 seconds per user | 1,000                 | Tenant-level token bucket (100 req/10sec burst)       |
| Queries per day                  | 1,000,000,000         | Spread syncs via cron; avoid concurrent full syncs    |
| File exports                     | Subject to user quota | Throttle export calls; use exponential backoff on 429 |

Resilience pattern (identical to SharePoint):

- Exponential backoff with jitter on `429 Too Many Requests`
- Respect `Retry-After` header
- Circuit breaker per tenant (5 failures → 10-min open state)
- Dead letter queue for failed file processing (retry up to 3x, then alert)

---

## 8. Security Considerations

1. **SSRF protection**: File download URLs must be validated to match `*.googleapis.com` and `*.google.com` domains only.
2. **Malware scanning**: Files downloaded from Google Drive must pass ClamAV scan before ingestion (same as document upload pipeline in `20-document-upload-architecture.md`).
3. **Sensitive data detection**: Run PII/secrets scanner on extracted text before indexing. Google Docs may contain credentials, PII, etc.
4. **Service account key rotation**: Platform must support key rotation without sync interruption. Store new key → validate connection → replace old key.
5. **Scope minimization**: Only `drive.readonly` and `drive.metadata.readonly` scopes. Never request write access.
6. **Webhook verification**: All incoming webhook calls must verify the `X-Goog-Channel-Token` header against stored tenant JWT.

---

## 9. Phased Rollout Plan

| Phase                          | Deliverable                                                                                                                     |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **Phase 3 (Auth Flexibility)** | Add Google Drive as third SSO-adjacent integration; implement credential storage and connection validation                      |
| **Phase 4 (Agentic Upgrade)**  | Full sync worker with incremental sync, folder browsing API, admin UI                                                           |
| **Phase 5 (Cloud Agnostic)**   | Google Drive as alternative to SharePoint for non-Microsoft customers; abstract `CloudStorageConnector` interface covering both |

The Google Drive connector should share the `CloudStorageConnector` abstract interface with SharePoint:

```python
class CloudStorageConnector(ABC):
    @abstractmethod
    async def validate_connection(self) -> ConnectionStatus: ...

    @abstractmethod
    async def list_top_level_containers(self) -> list[Container]: ...

    @abstractmethod
    async def list_folders(self, container_id: str, parent_id: Optional[str]) -> list[Folder]: ...

    @abstractmethod
    async def list_files(self, folder_id: str) -> list[FileMetadata]: ...

    @abstractmethod
    async def download_file(self, file_id: str, metadata: FileMetadata) -> bytes: ...

    @abstractmethod
    async def get_changes(self, page_token: str) -> tuple[list[FileChange], str]: ...
```

SharePoint and Google Drive both implement this interface, enabling the sync worker to be connector-agnostic.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
