# Google Drive User Flows

**Persona**: Tenant Admin (Organization IT Administrator)
**Scope**: Setting up and managing Google Drive sync for a tenant
**Role**: `tenant_admin` (scope: tenant)
**Date**: 2026-03-05

---

## Phase Mapping

| Flow | Flow Name                              | Built in Phase | Notes                                  |
| ---- | -------------------------------------- | -------------- | -------------------------------------- |
| 01   | Google Drive Connection Setup          | Phase 4        | Service account or OAuth setup         |
| 02   | Folder Selection and Configuration     | Phase 4        | Browse and select folders to sync      |
| 03   | First Sync and Validation              | Phase 4        | Monitor initial index population       |
| 04   | Ongoing Sync Management                | Phase 4        | Schedule changes, add/remove folders   |
| 05   | Sync Error Recovery                    | Phase 4        | Handle auth failures, API limits       |
| 06   | Tenant Migration (SharePoint → GDrive) | Phase 5        | Switch from SharePoint to Google Drive |

---

## 1. Google Drive Connection Setup

**Trigger**: Tenant admin navigates to Settings > Integrations > Google Drive.

```
Start: Tenant admin clicks [+ Add Integration] > [Google Drive]
  |
  v
[Choose Authentication Method]
  |-- (•) Google Workspace (Service Account)
  |       └── "Recommended for organizations using Google Workspace"
  |-- ( ) Personal / Non-Workspace (OAuth 2.0)
  |       └── "For individual Google accounts or non-Workspace setups"
  |
  +-- BRANCH: Service Account
  |     |
  |     v
  |   [Instructions screen shown]
  |     |-- "1. Create a Google Cloud project at console.cloud.google.com"
  |     |-- "2. Enable the Google Drive API"
  |     |-- "3. Create a Service Account"
  |     |-- "4. Download the JSON key file"
  |     |-- "5. Grant domain-wide delegation in Google Admin Console"
  |     |    Required scopes:
  |     |    • https://www.googleapis.com/auth/drive.readonly
  |     |    • https://www.googleapis.com/auth/drive.metadata.readonly
  |     |
  |     v
  |   [Upload Service Account Key]
  |     |-- Drag-drop or click to upload JSON key file
  |     |-- OR: Paste JSON content into text area
  |     |
  |     v
  |   [Enter Google Workspace Domain]
  |     |-- Domain: [acmecorp.com            ]
  |     |-- Service Account will impersonate sync@acmecorp.com
  |     |
  |     v
  |   [Click: Validate Connection]
  |     |
  |     +-- SUCCESS: ✓ Connected to Google Workspace
  |     |     |-- "Accessible as: sync@acmecorp.com"
  |     |     |-- "Found 5 Shared Drives"
  |     |     └── [Proceed to Folder Selection]
  |     |
  |     +-- ERROR: Invalid service account key
  |     |     |-> "The JSON key is invalid or expired. Please re-download from Google Cloud Console."
  |     |     |-> [Try Again]
  |     |
  |     +-- ERROR: Domain-wide delegation not configured
  |           |-> "Service account lacks domain-wide delegation. Go to Google Admin Console:
  |                Security > API Controls > Domain-wide Delegation
  |                Add client ID: {service_account_client_id}
  |                Scopes: drive.readonly, drive.metadata.readonly"
  |           |-> [Recheck After Configuring]
  |
  +-- BRANCH: OAuth 2.0
        |
        v
      [Click: Connect with Google]
        |
        v
      [Redirect to Google OAuth consent screen]
        |-- Scopes requested: drive.readonly, drive.metadata.readonly
        |-- User sees: "mingai wants to access your Google Drive (read-only)"
        |
        v
      [User grants access]
        |
        v
      [Callback: tokens stored in vault]
        |
        +-- SUCCESS: ✓ Connected as user@gmail.com
        |     └── [Proceed to Folder Selection]
        |
        +-- ERROR: User denied access
              |-> "Access was denied. Please grant read access to Google Drive to continue."
              |-> [Try Again]
```

---

## 2. Folder Selection and Configuration

**Trigger**: Successful connection validation.

```
Start: Connection validated, entering folder selection
  |
  v
[Folder Browser loads]
  |
  v
[Browse Shared Drives (Service Account) or My Drive (OAuth)]

Shared Drives:
  ├── [✓] Company Policies          (Select this drive)
  │     └── Include subfolders: [✓]
  ├── [ ] Finance Reports
  │     └── [Browse →]
  │           ├── [ ] Q1 2026 Reports
  │           ├── [✓] Annual Reports    ← select specific subfolder
  │           └── [ ] Drafts
  └── [ ] Engineering Documentation

My Drive:
  └── [ ] Shared by others
        └── [Browse →]

[+ Add Folder by URL]  Enter: https://drive.google.com/drive/folders/{id}
                       └── [Add]

Selected Folders (2):
  • Company Policies (Shared Drive) — est. 342 files
  • Finance / Annual Reports — est. 47 files
  [✕ Remove]

  |
  v
[Configure Sync Settings]

File Types to Include:
  [✓] PDF          [✓] Word Documents (.docx)
  [✓] Spreadsheets (.xlsx)  [✓] Presentations (.pptx)
  [✓] Text Files (.txt)
  [✓] Google Docs (auto-export to .docx)
  [✓] Google Sheets (auto-export to .xlsx)
  [ ] Google Slides (auto-export to .pptx)

Max File Size: [100] MB  (files larger than this are skipped)

Sync Schedule:
  ( ) Every 1 hour
  ( ) Every 6 hours  ← recommended
  (•) Every 24 hours
  ( ) Custom cron: [0 2 * * *   ]  (daily at 2 AM)

Search Index:
  (•) Create new index: "Google Drive — Company Policies + Finance"
  ( ) Add to existing index: [Select Index ▼]

  |
  v
[Review and Save]

Summary:
  Folders: Company Policies, Finance/Annual Reports
  File types: PDF, Word, Excel, Sheets (Google), Docs (Google)
  Sync schedule: Every 24 hours (daily at 2 AM)
  Estimated initial sync: ~389 files, ~45 minutes

[Start Sync Now]   [Save Without Syncing]   [← Back]
```

---

## 3. First Sync and Validation

**Trigger**: Admin clicks "Start Sync Now".

```
Start: First sync initiated
  |
  v
[Sync Progress Screen]

Google Drive Sync — First Run
  Status: In Progress ●
  Started: 2026-03-05 10:30:00

Progress:
  Discovered: 389 files
  Processed:  ██████░░░░ 156 / 389 (40%)
  Indexed:    145 files
  Failed:     0 files
  Skipped:    11 files (too large or unsupported type)

Current file: "Annual Report 2024.pdf"

[View Logs]   [Cancel Sync]

  |
  v
[Sync completes]

✓ Sync Complete

Summary:
  Duration: 38 minutes
  Files indexed: 378
  Files skipped: 11 (see details)
  Errors: 0

Skipped files (11):
  • strategy_presentation_draft_v7_FINAL_v2.pptx — 102 MB (exceeds 100 MB limit)
  • recording_board_meeting.mp4 — 845 MB (unsupported file type)
  • ... (9 more)

Search Index "Google Drive — Company Policies + Finance":
  Documents: 378
  Status: Ready ✓
  Estimated coverage: 2,340 pages

[View Index]   [Configure Roles for This Index]   [Done]

  |
  +-- ERROR: Partial failure (some files failed)
        |
        v
      [Sync completed with warnings]

      ✓ 361 files indexed successfully
      ⚠ 17 files failed (see details)

      Failed files:
        • encrypted_confidential.pdf — "File encrypted with password, cannot extract text"
        • corrupted_doc.docx — "File corrupted, unable to parse"

      [Download Error Report]   [Retry Failed Files]   [Done]
```

---

## 4. Ongoing Sync Management

**Trigger**: Tenant admin visits Settings > Integrations > Google Drive.

```
Google Drive Integration — Active
  Status: Active ✓
  Last sync: 2026-03-05 02:00 AM (5 hours ago)  ✓ Success
  Next sync: 2026-03-05 02:00 AM (19 hours)

Connected as: sync@acmecorp.com (Service Account)

Synced Folders:
  | Folder                       | Files | Last Change  | Status |
  |------------------------------|-------|--------------|--------|
  | Company Policies (Full Drive)| 342   | 2 hours ago  | ✓ Sync |
  | Finance / Annual Reports     | 47    | 3 days ago   | ✓ Sync |

Actions:
  [+ Add Folder]   [Edit Schedule]   [Sync Now]   [Disconnect]

  |
  +-- FLOW: Add a folder
  |     └── Opens folder browser (same as Flow 02)
  |
  +-- FLOW: Edit Schedule
  |     |
  |     v
  |   [Schedule Editor]
  |     Current: Daily at 2 AM
  |     Change to: ( ) Every 1h  ( ) Every 6h  (•) Daily  ( ) Custom
  |     [Save Schedule]
  |
  +-- FLOW: Sync Now (manual trigger)
  |     |
  |     v
  |   [Confirm: Run sync now? Last sync was 5 hours ago.]
  |   [Confirm]  [Cancel]
  |     |
  |     v
  |   [Sync progress screen] (same as Flow 03)
  |
  +-- FLOW: Disconnect Google Drive
        |
        v
      [Warning dialog]
        "Disconnecting will:
         ✗ Stop future syncs
         ✗ Remove sync configuration
         ✓ Keep existing indexed documents (they remain searchable)

         Do you want to also delete the indexed documents?"

        ( ) Keep indexed documents (recommended)
        ( ) Delete indexed documents from search index

        [Confirm Disconnect]   [Cancel]
```

---

## 5. Sync Error Recovery

**Trigger**: Platform sends error notification — sync job failed.

```
[Email / In-app notification received]
  Subject: "Google Drive sync failed — acmecorp.com"
  "The scheduled sync at 2:00 AM failed. Reason: Authentication error."

  [View Details]
  |
  v
[Sync Error Detail page]

Last Sync: FAILED ✗
Time: 2026-03-05 02:00 AM
Error: "Service account token expired or permissions revoked"

  |
  +-- CASE: Token expired / permission revoked
  |     |
  |     v
  |   [Revalidate Connection screen]
  |     "The service account key may have been rotated by your Google Workspace admin.
  |      Please upload the new service account key."
  |
  |     [Upload New Key File]
  |       |
  |       v
  |     [Validate Connection]
  |       |-- SUCCESS → resume sync schedule
  |       |-- FAILURE → escalate to admin
  |
  +-- CASE: API quota exceeded
  |     |
  |     v
  |   [Information message]
  |     "Google Drive API quota exceeded. Next retry in 4 hours.
  |      This usually resolves automatically. If it persists:
  |      • Reduce sync frequency (currently: every 1 hour)
  |      • Or contact platform support."
  |
  |     [Change Sync Frequency]
  |
  +-- CASE: Folder no longer accessible
        |
        v
      [Warning]
        "The following folders are no longer accessible:
         • /Shared Drives/Finance Reports

         The folder may have been deleted, moved, or permissions revoked.

         Options:"

        [Remove This Folder]   [Browse and Reselect]   [Ignore]
```

---

## 6. Tenant Migration: SharePoint → Google Drive

**Trigger**: Tenant admin wants to switch primary knowledge source from SharePoint to Google Drive.

```
Start: Tenant has active SharePoint sync + wants Google Drive
  |
  v
[Both integrations can run simultaneously]

Current Integrations:
  SharePoint ✓ Active    Last sync: 1 hour ago    Index: "SharePoint - HR"
  Google Drive ✓ Active  Last sync: 30 min ago    Index: "Google Drive - Policies"

Note: Users can query both indexes simultaneously.
No need to migrate — both can coexist.

  |
  +-- BRANCH: Admin wants to fully replace SharePoint with Google Drive
        |
        v
      [Plan migration]

      Step 1: Ensure Google Drive folders mirror SharePoint content
        [View overlap analysis] → Shows: 87% content overlap detected

      Step 2: Disable SharePoint sync (keep existing index)
        [Pause SharePoint Sync]

      Step 3: Verify Google Drive index is comprehensive
        [Run test queries against Google Drive index]
        [Compare results with SharePoint index]

      Step 4 (optional): Delete SharePoint index
        "Warning: This permanently removes 1,234 documents from search.
         Users will no longer find SharePoint-sourced content."

        [Delete SharePoint Index]  [Keep Both Indexes]
```

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
