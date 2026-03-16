# 20 — End User: Conversation Management Flows

**Date**: 2026-03-10
**Personas**: End User (knowledge worker), Tenant Admin (oversight)
**Domains**: Conversation Search, Conversation Sharing, Conversation Export, Conversation Organization

---

## Flow 1: Conversation Search

**Trigger**: User needs to find a specific conversation from 2 weeks ago where they discussed vendor contract terms. They have 40+ conversations in history and can't scroll through all of them.
**Persona**: End User
**Entry**: Chat sidebar → Search icon / search bar above conversation list

```
STEP 1: Access Conversation Search
  User opens the chat interface.
  Sidebar shows conversation history list (newest first):
    Today
      → HR Policy questions
      → Q4 budget analysis
    Yesterday
      → Team capacity planning
      → Onboarding checklist review
    Last week
      ...

  User clicks the search icon 🔍 at the top of the sidebar,
  OR types in the search bar that appears above the conversation list.

  Search bar opens with placeholder text:
    "Search conversations..."

STEP 2: Enter Search Query
  User types: vendor contracts
  Search executes as user types (debounced — triggers after 300ms pause)

  Results appear inline in the sidebar (replacing the conversation list):

    ─── 3 conversations found ─────────────────────────────────

    📄 Standard vendor payment terms          Mar 8, 2026
       "...standard NDA clause covers confidentiality for all vendor
        contracts including payment terms net 30..."

    📄 Legal Finance — Q1 vendor review       Feb 28, 2026
       "...three key vendors identified. Contracts are in the legal
        folder, accessible via SharePoint sync..."

    📄 Contract renewal discussion             Feb 14, 2026
       "...the vendor contract was last renewed in 2024. Based on
        your uploaded renewal checklist, the next review is..."

    ─── No more results ───────────────────────────────────────
    Tip: Try broader terms like "contract" or "payment"

STEP 3: Inspect Search Results
  Each result shows:
    - Conversation title (first message or auto-generated title)
    - Date of conversation
    - Snippet: matched text excerpt with search term highlighted (bold)
    - Source type icon: 📄 chat, 📤 if user uploaded a document in that conversation

  User clicks "Standard vendor payment terms" conversation
  Conversation loads with the matched text automatically scrolled into view
  Matched terms highlighted in the message where they appear

STEP 4: Navigate Within Search Results
  After opening a conversation, user sees:
    "Search: vendor contracts  — 3 conversations found  ← Prev | Next →"
    This toolbar stays visible while in search mode

  User clicks "Next →" to navigate to the next matching conversation without
  going back to the sidebar first.
  This is useful for quickly scanning multiple conversations.

STEP 5: Refine Search
  User types more specific query: "vendor contracts NDA"
  Results narrow to 1 conversation
  User finds exactly what they needed

  Search history: recent searches stored locally (this session only)
  Last 5 searches appear as quick-select chips below the search bar:
    vendor contracts | HR policy | Q4 budget | capacity | onboarding

  Clear button (×) next to search bar returns to full conversation list

STEP 6: Advanced Search (Optional)
  User clicks "Advanced" link below search bar:

    Date range:     [From: ________] [To: ________]
    Agent used:     [All agents ▼]
    Has documents:  [ ] Only conversations with uploaded documents
    Mode:           [All ▼] [Standard | Research | Agent]

  User filters: date range Feb 1 - Feb 28
  Results narrow: only February conversations matching "vendor contracts"

  Advanced search is saved for the session; user can clear with "Reset filters"
```

**What gets searched**:

- Conversation titles
- Message content (user queries and AI responses)
- Uploaded document names (if documents were attached in a conversation)

**What does NOT get searched** (for performance and privacy):

- Content of indexed company knowledge base documents (SharePoint/Drive — those are in the KB, not conversation history)
- Conversation metadata only visible to admins (audit data)

**Edge Cases**:

- No results found: "No conversations match 'quantum computing'. Try different keywords."
- Very large history (500+ conversations): Search is index-backed — responds in <500ms regardless of history size
- Search while streaming is active: search is available even while a response is streaming in another tab/session

---

## Flow 2: Conversation Sharing (Link-Based)

**Trigger**: User had a productive research conversation with the AI about Q3 competitive analysis and wants to share the key findings with their manager, who is also a mingai user.
**Persona**: End User (sharer), Another End User (recipient)
**Entry**: Active conversation → Share button

```
STEP 1: Initiate Share
  User has just completed a research conversation:
    "Competitive landscape Q3 2026 — APAC"
  The conversation contains 6 exchanges with sources, charts referenced, and a
  detailed AI summary.

  User clicks the share icon in the conversation header:
    Options appear:
      [◉] Share with workspace members (internal link)
      [ ] Export as PDF
      [ ] Export as Markdown
      [Cancel]

    Note: "Sharing gives recipients a read-only view of this conversation.
    They can read but cannot reply to it."

STEP 2: Configure Share Settings
  User selects "Share with workspace members"

  Share configuration:
    Access:
      [◉] Anyone in the workspace with the link can view
      [ ] Specific people (enter email addresses)

    Expiry:
      [◉] No expiry (link active until manually revoked)
      [ ] Expires in: [7 days | 30 days | custom date]

    Include:
      [✓] All messages in this conversation
      [✓] Sources panel (documents cited)
      [ ] Personal memory context (excluded by default — contains profile data)

  User keeps defaults: workspace-wide link, no expiry, all messages included.
  Clicks "Create Share Link"

STEP 3: Receive Share Link
  System generates a secure, opaque share link:
    https://acme.mingai.io/shared/cxn_8aB3kXm2pQ9r

  The link is displayed with copy button.
  User copies the link and pastes it in a Slack message to their manager:
    "@sarah here's the Q3 APAC competitive analysis I was working on: [link]"

STEP 4: Recipient Views Shared Conversation
  Sarah (manager) clicks the link in Slack.
  Browser opens the shared conversation view:

    ┌─────────────────────────────────────────────────────────┐
    │ 🔗 Shared Conversation                    [View only]  │
    │                                                         │
    │ Competitive landscape Q3 2026 — APAC                    │
    │ Shared by: tom.w@acme.com · Mar 10, 2026               │
    │                                                         │
    │ [User] What are the main competitors in APAC for...     │
    │                                                         │
    │ [AI] Based on the market research documents...          │
    │       ↳ AUTO · ANALYST · 0.91 confidence               │
    │       "The three main competitors are..."               │
    │       📄 3 sources                                      │
    │                                                         │
    │ [User] Can you summarize the key differentiators?       │
    │ [AI] Summary: ...                                       │
    │                                                         │
    │                                                         │
    │  [Continue this research in your own chat →]           │
    └─────────────────────────────────────────────────────────┘

  Sarah sees the full read-only conversation.
  She can expand sources (📄 3 sources) to see document references.
  She CANNOT reply or continue this specific conversation.

STEP 5: Recipient Continues Research (Fork)
  Sarah finds the analysis compelling and wants to explore further.
  She clicks: [Continue this research in your own chat →]

  This opens a NEW conversation for Sarah with context:
    "I am continuing research based on a shared conversation about the APAC
     competitive landscape. Here is a summary of the prior research: [summary]
     My question: [Sarah can type her question here]"

  Sarah's new conversation is entirely separate from Tom's original.
  Tom does not see Sarah's follow-up — it's private to Sarah.
  This is not true collaboration (Phase 5+) — it's a research fork.

STEP 6: Manage Shared Links
  Tom can see and manage all shares he has created:
  Conversation menu → "Manage shares"

    Active shares for this conversation:
      Link: cxn_8aB3kXm2pQ9r | Created: Mar 10 | Views: 3 | No expiry
      [Copy link] [Revoke]

  Tom can revoke the link at any time:
    After revocation: anyone visiting the link sees:
    "This shared conversation is no longer available."

  Tom's share history (across all conversations):
    Shows all active shares with view counts and expiry dates
    Bulk revoke: "Revoke all active shares"

STEP 7: Recipient Not in Workspace
  If Sarah's email is not a mingai user in the same workspace:
  Sarah clicks the link → sees login gate:
    "This shared conversation is from Acme Corp's workspace.
     Please sign in with your Acme Corp account to view it."
  If Sarah doesn't have an account: she cannot view it.
  Note: Links cannot be shared externally (different workspace, no account).
  External sharing is a Phase 5+ feature (requires additional security controls).
```

**Edge Cases**:

- User shares a conversation that contains sensitive document excerpts → The shared view shows the AI response (which may quote documents) but does not link to the source documents directly — recipient sees the conversation as-is, not the underlying KB
- Recipient's role does not have access to a KB referenced in the conversation → Recipient can read the conversation including AI responses, but cannot initiate their own queries to that KB if they lack access
- Conversation shared link goes viral within the company (100+ views) → System does not limit views; this is fine since access is workspace-scoped
- User deletes the original conversation → All associated share links immediately return 404: "This conversation no longer exists."

---

## Flow 3: Conversation Export

**Trigger**: User wants to save a research conversation as a PDF to include in a quarterly report, or export as Markdown to paste into a Notion doc.
**Persona**: End User
**Entry**: Conversation header → Export / ⋮ menu → Export

```
STEP 1: Access Export Options
  User opens a completed conversation.
  Clicks "⋮" (more options) in the conversation header.
  Selects "Export conversation"

  Export options panel:
    Format:
      [◉] PDF — formatted document, includes sources summary
      [ ] Markdown — plain text, portable to any tool
      [ ] JSON — raw data (for developers / system integrations)

    Include:
      [✓] All messages (user + AI)
      [✓] Source citations (document names and scores)
      [ ] Metadata (timestamps, model used, latency) — optional, disabled by default
      [ ] Personal memory context (disabled by default — privacy)

    Date range (for long conversations):
      [◉] Full conversation
      [ ] From message: [dropdown of messages]

STEP 2: PDF Export
  User selects PDF.
  Clicks "Export"
  System generates PDF in <5 seconds.

  PDF structure:
    ─────────────────────────────────────────────────
    Acme Technologies AI Workspace
    Conversation Export — March 10, 2026

    "Competitive landscape Q3 2026 — APAC"
    ─────────────────────────────────────────────────
    User: What are the main competitors in APAC for...

    AI Response (AUTO · ANALYST · 0.91 confidence):
    "The three main competitors are..."

    Sources consulted:
    1. APAC Market Report Q3 2025.pdf (score: 0.94)
    2. Competitor Intelligence Brief.docx (score: 0.87)
    3. Regional Sales Analysis.pptx (score: 0.81)
    ─────────────────────────────────────────────────
    [Next exchange...]
    ─────────────────────────────────────────────────
    Page 3 of 7

  PDF downloads to user's device automatically.

STEP 3: Markdown Export
  User changes format to Markdown.
  Clicks "Export"
  System generates .md file:

    # Competitive landscape Q3 2026 — APAC
    *Exported from Acme Technologies AI Workspace · March 10, 2026*

    ---

    **User**: What are the main competitors in APAC for...

    **AI** (AUTO · ANALYST · 0.91 confidence):
    The three main competitors are...

    > Sources: APAC Market Report Q3 2025, Competitor Intelligence Brief, Regional Sales Analysis

    ---

    **User**: Can you summarize the key differentiators?

    **AI**:
    Summary: ...

  User opens the .md file in Notion, Obsidian, or any text editor.
  Markdown preserves the conversation structure and is easily readable.

STEP 4: Data Retention and Export Rights
  Users can export their own conversation history at any time.
  Export is limited to conversations the user participated in (not other users').
  System logs exports in audit trail (for compliance): "User tom.w exported conversation
  cxn_XXXXXX at 14:23 UTC on March 10, 2026"

  Tenant admin can disable exports for their workspace if data governance requires:
    Settings → Data & Privacy → "Disable conversation export for all users"
    Users then see: "Export is disabled by your workspace administrator."

STEP 5: Bulk Export (History Download)
  User wants to export ALL their conversation history before leaving the company.
  Settings → Privacy → Download My Data

  System compiles:
    - All conversations (JSON format)
    - All personal memory notes
    - Profile preferences

  "Your data export is being prepared. You'll receive an email with a download link
  when it's ready (~5 minutes)."

  Download link valid for 48 hours.
  ZIP file includes:
    conversations/
      YYYY-MM-DD_conversation-title.json (one file per conversation)
    memory/
      notes.json
    profile/
      preferences.json
```

---

## Flow 4: Conversation Organization and Management

**Trigger**: User has 100+ conversations and wants to find conversations quickly, rename auto-titled ones, and delete old conversations.
**Persona**: End User
**Entry**: Sidebar conversation list

```
STEP 1: Conversation List Overview
  Sidebar shows conversations grouped by time:

    TODAY
      📄 Vendor contract review           [...]
      📄 Q4 budget planning session       [...]

    YESTERDAY
      📄 Team capacity analysis           [...]
      📄 New employee onboarding guide    [...]

    LAST WEEK
      📄 Competitive landscape Q3         [...]
      📄 0c4b91f... [untitled — 3 msg]    [...]  ← auto-titled, generic

    LAST MONTH (collapsed)
      [Show 47 conversations]

STEP 2: Rename a Conversation
  User hovers over the auto-titled conversation "0c4b91f...":
  Tooltip shows first query: "What are the HR guidelines for..."
  Three-dot (⋮) menu appears on hover

  User clicks ⋮ → "Rename"
  Inline text input replaces title:
    [HR guidelines for remote contractors        ]
  User types the name, presses Enter
  Conversation renamed. Immediately visible in sidebar.

STEP 3: Delete a Conversation
  User identifies an old test conversation: "test test test"
  Clicks ⋮ → "Delete"

  Confirmation modal:
    "Delete 'test test test'?
     This permanently removes the conversation and all messages.
     This cannot be undone."
  [Delete] [Cancel]

  User clicks "Delete"
  Conversation removed from sidebar immediately.
  If this conversation had any active share links:
    Those links now return 404 automatically.

STEP 4: Star / Bookmark Important Conversations
  User wants to bookmark the "Competitive landscape Q3 2026" conversation.
  Clicks ⋮ → "Star conversation"
  A ⭐ star appears next to the conversation title.

  Sidebar adds "Starred" section at the top:
    STARRED
      ⭐ Competitive landscape Q3 2026    Mar 10
      ⭐ Contract renewal review          Feb 14

    TODAY
      📄 Vendor contract review
      ...

  Starred conversations remain pinned regardless of age.
  User can remove star: ⋮ → "Remove star"
  Maximum starred conversations: 20 (to maintain a useful list, not a second inbox)

STEP 5: Continue a Past Conversation
  User wants to continue researching from a previous conversation.
  Clicks on "Competitive landscape Q3 2026" in the sidebar.
  Conversation loads in the main chat area — all previous messages visible.

  User types a new message:
    "What about the Southeast Asia market specifically?"
  Message sent — conversation continues from where it left off.
  The AI has context of all previous messages in this conversation.

  Context window management (transparent to user):
  If conversation is very long (>50 messages):
    System automatically summarizes older context to fit within model context window.
    User does not see this — responses remain coherent.
    If user explicitly references a very early message: AI may not have it in context.
    User can re-ask with explicit quotation if needed.
```

---

## Flow 5: Session Expiry and Conversation Recovery

**Trigger**: User's JWT token expires mid-conversation (15-minute access token), or browser tab refreshes. User should not lose their work.
**Persona**: End User
**Entry**: Active chat session (token expiry scenario)

```
STEP 1: Token Nearing Expiry (Silent Refresh)
  User has been chatting for 14 minutes (access token = 15 minutes).
  Frontend auto-refreshes access token 2 minutes before expiry:
    Sends refresh token to backend → receives new 15-minute access token
    User notices nothing — conversation continues uninterrupted.
  This happens silently on every query.

STEP 2: Refresh Token Also Expired (Forced Re-Login)
  Refresh token is valid for 7 days.
  User who hasn't logged in for 7+ days will be forced to re-authenticate.

  Mid-conversation:
    User submits a message.
    Request returns 401 (refresh token expired).
    Frontend shows non-blocking notification:
      "Your session has expired. Please sign in again to continue."
      [Sign In]
    Chat input disabled until re-authentication.

  User clicks "Sign In" → SSO redirect → returns to the same conversation.
  All previous messages in the conversation are preserved (saved to DB on each exchange).
  User can continue from where they left off.

STEP 3: Browser Refresh Mid-Conversation
  User accidentally refreshes the tab while waiting for a response.
  Page reloads.
  Conversation is restored from server state:
    - Previous messages are reloaded from DB
    - If a response was being streamed when refresh happened:
      The streaming response may be partially saved or incomplete
    - If partially saved: last AI message shows as-is (partial response)
    - User sees: "(Response may be incomplete — the page was refreshed)"
    - User can re-ask the question or continue with partial context

STEP 4: Offline State Recovery
  User loses network connection during streaming.
  Reconnect indicators appear (documented in flow 08 of 03-end-user-flows.md).
  When connection restored:
    - If server completed the response: response loads from SSE buffer
    - If server timed out: user sees error, can retry
  Conversation history is always recoverable from the DB regardless of network state.

STEP 5: Browser Crash Recovery
  User's browser crashes during an active conversation.
  User re-opens browser → navigates to mingai.
  Previous conversation is in history (all messages persisted).
  User clicks the conversation to resume.
  Any in-progress message that was being streamed when crash happened:
    - If backend completed: message is in DB, shows correctly
    - If backend did not complete: last message may be partially saved or absent
    - User re-sends the message if needed
```

---

## Flow 6: Personal Memory Notes — Review and Manage

**Trigger**: User wants to see what the AI has learned about them from past conversations (profile memory), edit an incorrect memory, or delete a note.
**Persona**: End User
**Entry**: User profile menu → "My Memory" or Settings → Privacy → Memory Notes

```
STEP 1: Access Memory Notes
  User clicks their avatar in the top-right corner.
  Dropdown shows: My Profile | My Memory | Sign Out

  User clicks "My Memory"
  Opens a panel showing learned notes about the user:

    MY MEMORY — What the AI knows about you
    ─────────────────────────────────────────
    These are notes saved from your conversations to personalize responses.
    You can edit or delete any of these.

    📌 Work context
      "Works on the Finance team at Acme Corp"
      "Primary focus: vendor contracts and cost analysis"
      Source: Conversation from Mar 8 | [Edit] [Delete]

    📌 Preferences
      "Prefers concise responses with bullet points"
      "Always wants sources cited with document names"
      Source: Conversation from Feb 28 | [Edit] [Delete]

    📌 Projects
      "Currently working on Q3 APAC competitive analysis"
      "Contract renewal project with Legal team (ongoing)"
      Source: Conversation from Mar 10 | [Edit] [Delete]

    📌 Communication style
      "Uses technical finance terminology — no simplification needed"
      Source: Conversation from Feb 14 | [Edit] [Delete]

STEP 2: Edit an Incorrect Memory
  The "Works on Finance team" note is outdated — user moved to Strategy team.
  User clicks [Edit] next to that note.
  Inline edit box opens:
    [Works on the Finance team at Acme Corp     ]
  User changes to: "Works on the Strategy team at Acme Corp (transferred Mar 2026)"
  Clicks "Save"
  Note updated immediately — future responses will use updated context.

STEP 3: Delete a Memory Note
  The "Q3 APAC competitive analysis" project is complete.
  User clicks [Delete] next to that note.
  Confirmation: "Delete this memory note? The AI will no longer personalize
  responses based on this context."
  User clicks "Delete" → note removed.

STEP 4: Clear All Memory
  User wants a clean slate (or is ending employment, privacy preference).
  At the bottom of the memory panel:
    [Clear all memory notes]
  Confirmation modal:
    "Delete all 8 memory notes? This cannot be undone.
     Future responses will use no personal context until new notes are learned."
  User confirms → all notes deleted.
  Profile memory score resets to 0.

STEP 5: Opt Out of Memory Learning
  User does not want future conversations to build memory notes.
  Toggle at top of memory panel:
    "Allow AI to learn from my conversations [Toggle: ON]"
  User turns OFF:
    "AI will not save new notes from your conversations.
     Existing notes are preserved. [Clear existing notes] if desired."
  User keeps existing notes but stops future learning.
  This preference persists across sessions.
```

---

## Edge Cases

### E1: Conversation Search Doesn't Find Old Conversations

```
User searches "contract terms" and gets 0 results despite having clear memory of
discussing it last month.
Reason: Old conversations (before Mar 2026) may not be full-text indexed if
  search index was deployed after their creation.
System shows: "If you have older conversations that aren't appearing, try scrolling
  to the 'Last Month' section in your history."
Long-term fix: Background indexing job populates search index for all existing conversations.
Admin can trigger reindex from Settings → Data → Rebuild Conversation Search Index.
```

### E2: Shared Link Accessed by Unauthenticated User

```
User shares a link, recipient is not logged in.
Recipient sees: login gate (workspace SSO redirect).
After login, recipient is redirected back to the shared conversation.
If SSO fails: "Unable to authenticate. Contact your administrator."
External public links (no login required) are NOT supported in current scope.
```

### E3: Very Long Conversation Export

```
User has a 200-message research conversation (3 hours of back-and-forth).
PDF export takes 30 seconds.
System shows progress indicator: "Generating export... 67%"
PDF is 47 pages. Downloads successfully.
If export takes >60 seconds: "Your export is being generated. We'll email you a link."
```

### E4: Memory Note Contains Sensitive Information

```
User discusses a merger in a conversation — AI saves: "Working on Project Aquila
  (confidential merger with TechCorp)."
User realizes this is highly sensitive.
User immediately deletes the note from My Memory panel.
Note deleted — but the original conversation message still exists in history.
If user wants full deletion: they must also delete the conversation that generated the note.
Or: user turns off memory learning for sensitive projects.
```
