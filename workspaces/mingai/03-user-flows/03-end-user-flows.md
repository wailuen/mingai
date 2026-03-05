# End User Flows

**Persona**: Knowledge Worker (End User)
**Scope**: Chat, search, document upload, agent interaction
**Role**: `default` (scope: tenant) + custom index-access roles
**Date**: March 4, 2026

---

## Phase Mapping

| Flow | Flow Name                                | Built in Phase | Notes                                        |
| ---- | ---------------------------------------- | -------------- | -------------------------------------------- |
| 01   | First Login and Onboarding               | Phase 1        | SSO login, JWT session, onboarding tour      |
| 02   | Standard Chat (Query -> RAG -> Response) | Phase 1        | Core RAG pipeline, streaming responses       |
| 03   | Research Mode (Multi-Index Deep Search)  | Phase 1        | Multi-index parallel search, deep synthesis  |
| 04   | Document Upload                          | Phase 1        | Personal document indexing and search        |
| 05   | Agent Delegation (Research Agent)        | Phase 4        | Kaizen multi-agent orchestration             |
| 06   | Internet Search Fallback                 | Phase 1        | Tavily web search when KB insufficient       |
| 07   | Conversation History                     | Phase 1        | History, search, share, export               |
| 08   | Failure Paths                            | Phase 1        | Timeout, rate limit, session expiry handling |
| 09   | User Response Feedback (Thumb Up/Down)   | Phase 1        | Rating, tags, comments, admin review queue   |

---

## 1. First Login and Onboarding

**Trigger**: User receives invitation email or navigates to tenant URL.

### SSO First Login

```
Start
  |
  v
[User navigates to https://{tenant-slug}.mingai.ai]
  |
  v
[Login page displayed]
  |-- "Sign in with Microsoft" (or configured SSO provider)
  |-- Tenant branding: logo, color, organization name
  |
  v
[Click SSO button]
  |
  v
[Redirect to identity provider (Azure AD / Auth0)]
  |-- User enters corporate credentials
  |-- MFA challenge (if configured by IdP)
  |
  +-- ERROR: User not in Azure AD tenant
  |     |-> "You are not authorized for this organization."
  |     |-> Contact your IT administrator.
  |
  +-- ERROR: SSO provider unreachable
  |     |-> "Authentication service unavailable. Please try again."
  |     |-> If persistent: tenant admin enables temporary fallback
  |
  v
[Redirect back with authorization code]
  |
  v
[Backend processes login]
  |-- Exchange code for tokens
  |-- Extract user profile (email, name, department, groups)
  |-- Check: user exists in tenant database?
  |
  +-- EXISTING USER: load profile, update last_login
  |
  +-- NEW USER (first login):
  |     |-- Create user record in tenant database
  |     |-- Assign default role ("User")
  |     |-- Sync Azure AD groups -> map to tenant roles
  |     |-- Generate JWT with tenant_id, roles, permissions
  |
  v
[JWT issued, session established]
  |-- Access token: 8-hour expiry
  |-- Refresh token: 7-day expiry
  |-- HTTP-only cookie + Bearer token
  |
  v
[First-time onboarding tour]
  |-- Step 1: "Welcome to mingai" -- brief product intro
  |-- Step 2: "Ask anything" -- show chat interface, explain capabilities
  |-- Step 3: "Your data sources" -- show which indexes you can access
  |   |-- Based on role: "You have access to HR Policies, Finance Reports"
  |-- Step 4: "Upload documents" -- explain personal document feature
  |-- Step 5: "Provide feedback" -- explain thumbs up/down on responses
  |-- "Skip tour" option available at any step
  |
  v
[Redirect to main chat interface]
  |
  v
End
```

**Outcome**: User authenticated with correct permissions, oriented to key features.

---

## 2. Standard Chat (Query -> RAG -> Response)

**Trigger**: User types a question in the chat interface.

```
Start
  |
  v
[User types query in chat box]
  |-- Example: "What is our travel reimbursement policy?"
  |-- Chat input supports: text, paste, keyboard shortcuts
  |
  v
[Submit query]
  |-- POST /api/v1/chat/stream (SSE endpoint)
  |-- Request includes: query, conversation_id, selected_indexes (optional)
  |
  v
[Backend: Intent Detection]
  |-- LLM analyzes query to determine:
  |   |-- Query type: factual, analytical, procedural, comparative
  |   |-- Language: auto-detected (respond in same language)
  |   |-- Domain hints: HR, finance, engineering, general
  |
  v
[Backend: Index Selection]
  |-- Filter by user's accessible indexes (RBAC check)
  |-- LLM-driven routing: which indexes likely have the answer?
  |   |-- "travel reimbursement" -> HR Policies index (high confidence)
  |   |-- "Q3 revenue" -> Finance Reports index
  |
  +-- User manually selected indexes? Use those instead.
  |
  +-- No relevant index found?
  |     |-> Check personal documents
  |     |-> Fall back to internet search (Tavily)
  |     |-> If still nothing: "I couldn't find information on this topic
  |     |   in your organization's knowledge base."
  |
  v
[Backend: RAG Pipeline]
  |-- Parallel search across selected indexes
  |-- Retrieve top-K chunks per index
  |-- Re-rank by relevance score
  |-- Build context window: query + retrieved chunks + system prompt
  |
  v
[Backend: LLM Synthesis]
  |-- Send context to LLM (Azure OpenAI / BYOLLM / tenant default)
  |-- Stream response tokens via SSE
  |
  v
[Frontend: Response Rendering]
  |-- Tokens appear in real-time (streaming)
  |-- Response includes:
  |   |-- Synthesized answer text
  |   |-- Source citations: [1] HR Policy Manual, p.42
  |   |-- Relevance scores per source
  |   |-- Confidence indicator (high / medium / low)
  |   |-- Language: matches query language
  |
  v
[User sees complete response]
  |
  +-- [Feedback: Thumbs up / Thumbs down]
  |     |-- Thumbs up: logged, improves future ranking
  |     |-- Thumbs down: opens feedback form
  |     |   |-- "What was wrong?" -- inaccurate, incomplete, irrelevant, wrong source
  |     |   |-- Optional: correct answer text
  |     |   |-- POST /api/v1/feedback
  |
  +-- [Follow-up question]
  |     |-- Conversation context maintained
  |     |-- Previous Q&A in context window
  |     |-> Return to "Submit query" step
  |
  +-- [Click source citation]
  |     |-- Opens source document (link to SharePoint, external URL)
  |     |-- If no link available: shows extracted chunk
  |
  v
End
```

**Error Paths**:

- LLM timeout (>30s) -> "Taking longer than expected. Please wait..." after 15s; hard timeout at 30s with "Unable to generate response. Try again."
- Rate limit hit -> "You've reached the query limit. Try again in {N} minutes."
- Index unreachable -> skip that index, search remaining; note: "Some data sources were unavailable"
- Empty result set -> attempt internet fallback before reporting no results

---

## 3. Research Mode (Multi-Index Deep Search)

**Trigger**: User selects "Research Mode" toggle or system detects complex query.

```
Start
  |
  v
[User activates Research Mode]
  |-- Toggle in chat toolbar
  |-- OR: system auto-suggests for complex queries
  |   |-- "Compare Q3 revenue projections with engineering headcount"
  |   |-- System: "This looks like a research question. Enable Research Mode?"
  |
  v
[Research Mode active -- UI changes]
  |-- Index selector expanded: multi-select all accessible indexes
  |-- Depth selector: Standard / Deep / Exhaustive
  |-- Source quality scoring visible
  |
  v
[User submits research query]
  |
  v
[Backend: Multi-Index Parallel Search]
  |-- Search ALL selected indexes simultaneously
  |-- Per-index results with relevance scores
  |-- Cross-index deduplication
  |
  v
[Backend: Source Quality Scoring]
  |-- Each source scored on:
  |   |-- Recency: how old is the document?
  |   |-- Authority: official policy vs. meeting notes
  |   |-- Relevance: semantic similarity to query
  |   |-- Coverage: does it address the full question?
  |-- Scores normalized 0-100
  |
  v
[Backend: Deep Synthesis]
  |-- LLM receives ALL high-quality sources
  |-- Prompt instructs: compare, contrast, synthesize
  |-- Identifies: agreements, contradictions, gaps
  |-- Longer, more detailed response (no token limit reduction)
  |
  v
[Frontend: Research Results Panel]
  |-- Main response: synthesized analysis
  |-- Source panel (collapsible):
  |   |-- Source 1: [Finance Q3 Report] Score: 92 | Finance Index
  |   |-- Source 2: [HR Headcount Plan] Score: 87 | HR Index
  |   |-- Source 3: [Board Presentation] Score: 74 | Executive Index
  |-- Conflict callout: "Source 1 and Source 3 show different projections"
  |-- Gap callout: "No data found for Q4 projections"
  |
  v
End
```

**Error Paths**:

- Too many indexes selected (>20) -> "Select up to 20 indexes for research mode"
- Research query too broad -> "Please refine your query. Suggestion: [narrower query]"
- Exhaustive search times out -> return partial results with note

---

## 4. Document Upload

**Trigger**: User clicks "Upload" button or drags file into chat area.

```
Start
  |
  v
[User action: drag-drop file or click upload button]
  |-- Supported formats: PDF, DOCX, PPTX, XLSX, TXT, MD, CSV
  |-- Max file size: 50 MB per file
  |-- Max total storage: per-user quota (plan dependent)
  |
  v
[Frontend: File validation]
  |
  +-- Invalid format -> "Unsupported file type. Supported: PDF, DOCX, ..."
  +-- Too large -> "File exceeds 50 MB limit."
  +-- Over quota -> "Storage limit reached. Delete old files to upload new ones."
  |
  v
[Upload initiated]
  |-- POST /api/v1/documents/upload (multipart form)
  |-- Progress bar displayed
  |
  v
[Backend: Document Processing Pipeline]
  |
  +-- Step 1: Store original in user's OneDrive (personal scope)
  |
  +-- Step 2: Text extraction
  |   |-- PDF: OCR if scanned, text extraction if digital
  |   |-- DOCX/PPTX: XML parsing
  |   |-- XLSX/CSV: cell-by-cell extraction with table structure
  |
  +-- ERROR: Extraction fails
  |     |-- Corrupted file -> "Could not process this file. Please try a different format."
  |     |-- Password-protected -> "File is password-protected. Please remove protection and retry."
  |     |-- Scanned PDF, OCR fails -> "Low quality scan. Try a clearer copy."
  |
  +-- Step 3: Chunking
  |   |-- Split text into semantic chunks (512-1024 tokens)
  |   |-- Preserve document structure (headings, sections)
  |
  +-- Step 4: Embedding generation
  |   |-- Generate vector embeddings for each chunk
  |   |-- Store in user-scoped personal index
  |
  +-- Step 5: Index update
  |   |-- Add to user's personal search index
  |   |-- Available immediately for search
  |
  v
[Frontend: Upload complete notification]
  |-- "Document indexed successfully"
  |-- "Found 42 pages, 156 sections"
  |-- "You can now ask questions about this document"
  |
  v
[User asks question about uploaded document]
  |-- Personal index automatically included in search
  |-- Private: only this user can access their uploads
  |-- RAG pipeline includes personal docs alongside enterprise indexes
  |
  v
End
```

---

## 5. Agent Delegation (Research Agent)

**Trigger**: User delegates a complex research task to an AI agent.

```
Start
  |
  v
[User recognizes task requires extended research]
  |-- Complex multi-step question
  |-- Multiple data sources needed
  |-- Time-consuming analysis
  |
  v
[Click "Delegate to Research Agent" button]
  |-- OR: type "research:" prefix to trigger agent mode
  |
  v
[Agent Configuration Panel]
  |-- Task description (what to research)
  |-- Scope: which indexes / MCP sources to use
  |-- Depth: Quick (5 min) / Standard (15 min) / Deep (30 min)
  |-- Output format: Summary / Detailed Report / Comparison Table
  |
  v
[Submit to agent]
  |-- POST /api/v1/agents/research/delegate
  |
  v
[Agent executes in background]
  |-- User can continue other chats (non-blocking)
  |-- Progress indicator in sidebar:
  |   |-- "Searching HR Policies..." (step 1/5)
  |   |-- "Analyzing Finance Reports..." (step 2/5)
  |   |-- "Cross-referencing sources..." (step 3/5)
  |   |-- "Synthesizing findings..." (step 4/5)
  |   |-- "Generating report..." (step 5/5)
  |
  +-- Agent hits dead end on a source
  |     |-> Tries alternative query reformulations
  |     |-> Falls back to internet search if KB insufficient
  |     |-> Notes gap in final report
  |
  +-- Agent discovers contradictory information
  |     |-> Flags contradiction in report
  |     |-> Presents both sides with sources
  |     |-> Recommends which source is more authoritative
  |
  v
[Agent completes]
  |-- SSE notification: "Research complete"
  |-- Browser notification (if enabled)
  |-- Email notification (if configured)
  |
  v
[User reviews results]
  |-- Full research report displayed
  |-- Sections: Executive Summary, Findings, Sources, Gaps
  |-- Iterative refinement:
  |   |-- "Go deeper on section 2"
  |   |-- "Include data from Bloomberg"
  |   |-- "Compare with last quarter"
  |   |-> Agent resumes from where it left off
  |
  v
End
```

**Error Paths**:

- Agent timeout (exceeds depth time limit) -> return partial results with "Research incomplete" flag
- All indexes unavailable -> "Cannot perform research. Data sources are temporarily unavailable."
- Agent stuck in loop -> circuit breaker stops after 3 retries on same query, returns best results so far

---

## 6. Internet Search Fallback

**Trigger**: Knowledge base search returns insufficient results.

```
Start
  |
  v
[RAG pipeline returns low-confidence results]
  |-- Relevance score below threshold (configurable, default: 0.3)
  |-- OR: no results from any index
  |
  v
[Decision: Internet fallback enabled?]
  |
  +-- NO (admin disabled) -> Return: "No results found in your organization's
  |   knowledge base for this query."
  |
  +-- YES -> Proceed
  |
  v
[Tavily web search executed]
  |-- Query sent to Tavily API
  |-- Scope: general web, news, or academic (auto-selected)
  |-- Results: top 5 web sources
  |
  v
[Source Credibility Assessment]
  |-- Each web source scored:
  |   |-- Domain authority (known trusted sources rank higher)
  |   |-- Recency (recent articles preferred)
  |   |-- Relevance to query
  |-- Low-credibility sources flagged: "Unverified web source"
  |
  v
[LLM synthesizes with web results]
  |-- Clear distinction in response:
  |   |-- "From your organization's knowledge base:" (if partial results)
  |   |-- "From web sources:" (Tavily results)
  |-- Each web citation shows: [Web] Source Name, URL, credibility score
  |
  v
[Response displayed with web indicator]
  |-- Banner: "This answer includes information from web sources"
  |-- Web sources clearly labeled
  |-- User can filter: "Show only enterprise results" / "Show all"
  |
  v
End
```

**Error Paths**:

- Tavily API timeout -> return KB-only results with "Web search unavailable" note
- Tavily rate limited -> queue and retry; if persistent, skip web results
- All sources low-credibility -> warn user: "Web results available but from unverified sources"

---

## 7. Conversation History

**Trigger**: User accesses past conversations.

```
Start
  |
  v
[Click conversation history icon in sidebar]
  |
  v
[Conversation List]
  |-- Sorted by: most recent first
  |-- Each entry: title (auto-generated from first query), date, preview
  |-- Retention: per-tenant policy (default: 365 days)
  |
  v
[Search conversations]
  |-- Full-text search across conversation titles and content
  |-- Filters: date range, has-citations, has-feedback
  |-- GET /api/v1/conversations?search={term}
  |
  v
[Click conversation to open]
  |-- Full conversation thread displayed
  |-- All messages, sources, feedback preserved
  |-- Can continue conversation from where it left off
  |
  v
[Share conversation]
  |-- Click "Share" button
  |-- Options:
  |   |-- Copy link (shareable within organization)
  |   |-- Export as PDF
  |   |-- Export as Markdown
  |
  +-- Sharing respects RBAC: recipient must have access
  |   to the same indexes to see full sources
  |
  +-- ERROR: Recipient lacks index access
  |     |-> Shared view shows response text but redacts
  |     |   source details they cannot access
  |
  v
[Export conversation]
  |-- Format: PDF or Markdown
  |-- Includes: all messages, sources, citations
  |-- Excludes: internal system prompts, raw embeddings
  |
  v
End
```

---

## 8. Failure Paths (Comprehensive)

These failure paths apply across all end-user flows.

### LLM Timeout

```
[Query submitted]
  |
  v
[LLM processing...]
  |-- 15 seconds elapsed: show "Taking longer than expected..."
  |-- 30 seconds elapsed: hard timeout
  |
  v
[Timeout response]
  |-- "Response generation timed out. This can happen with complex queries."
  |-- Suggestions:
  |   |-- "Try breaking your question into smaller parts"
  |   |-- "Try again (transient issue)"
  |-- Retry button (one click, same query)
  |
  +-- Repeated timeouts (3x same session)
  |     |-> "Persistent timeout detected. The LLM service may be experiencing
  |     |   high load. Please try again in a few minutes."
  |     |-> Logged as incident for tenant admin visibility
```

### No Results Found

```
[Search returns empty across all indexes]
  |
  v
[Response: "I couldn't find relevant information"]
  |-- Suggestions:
  |   |-- "Try rephrasing your question"
  |   |-- "Check if you have access to relevant knowledge bases"
  |   |-- "Upload a document if you have the information"
  |-- If internet fallback available: "Would you like me to search the web?"
  |-- Log as "unanswered query" for analytics (content gap detection)
```

### Rate Limit Hit

```
[User sends query]
  |
  v
[Rate limit check: 10 queries/minute exceeded]
  |
  v
[Response: 429 Too Many Requests]
  |-- "You've sent too many queries. Please wait {N} seconds."
  |-- Countdown timer displayed
  |-- Query queued: auto-submits when limit resets
  |-- If persistent: "Daily query limit reached. Limit resets at midnight UTC."
```

### Session Expiry

```
[User has been idle > 8 hours]
  |
  v
[Next action triggers token validation]
  |-- Access token expired
  |
  v
[Automatic refresh attempt]
  |-- Refresh token valid? -> new access token issued, seamless
  |-- Refresh token expired? -> redirect to login page
  |   |-- "Your session has expired. Please sign in again."
  |   |-- Unsaved draft preserved in local storage
  |   |-- After login: return to previous page with draft restored
```

### Tenant Suspended

```
[User attempts to log in]
  |
  v
[Tenant status: suspended]
  |
  v
[Login blocked]
  |-- "Your organization's access has been suspended."
  |-- "Please contact your IT administrator."
  |-- No access to any features, data, or history
```

---

## 9. User Response Feedback (Thumb Up/Down)

**Trigger**: User receives an AI response in chat and wants to rate its quality.
**Actors**: End User, Platform, Tenant Admin
**Phase**: Phase 1

### Happy Path (Thumb Up)

```
Start
  |
  v
[User receives AI response in chat]
  |-- Response displayed with source citations
  |-- Thumb up / thumb down icons appear below the response
  |
  v
[User clicks thumb-up icon]
  |
  v
[POST /api/v1/feedback]
  |-- Payload: {
  |     tenant_id,
  |     conversation_id,
  |     message_id,
  |     user_id,
  |     rating: +1,
  |     timestamp
  |   }
  |
  v
[Platform records feedback]
  |-- Stored in feedback table with tenant_id scoping (RLS)
  |-- Icon turns filled/highlighted (visual confirmation)
  |-- No further action required
  |
  v
End
```

### Thumb Down Flow

```
Start
  |
  v
[User clicks thumb-down icon]
  |
  v
[Platform shows optional tag selection]
  |-- Tags: [Inaccurate] [Incomplete] [Irrelevant] [Hallucinated] [Other]
  |-- User selects one or more tags (optional)
  |
  v
[Optional free-text comment field appears]
  |-- Placeholder: "Tell us more..."
  |-- Max length: 1000 characters
  |
  v
[User submits feedback (or dismisses)]
  |
  +-- DISMISS: No feedback recorded beyond the thumb-down click
  |     |-> Icon turns filled (thumb-down registered with rating: -1 only)
  |
  +-- SUBMIT: Full feedback recorded
  |     |
  |     v
  |   [POST /api/v1/feedback]
  |     |-- Payload: {
  |     |     tenant_id,
  |     |     conversation_id,
  |     |     message_id,
  |     |     user_id,
  |     |     rating: -1,
  |     |     tags: ["inaccurate", "hallucinated"],
  |     |     comment: "The policy cited was from 2023, not current.",
  |     |     timestamp
  |     |   }
  |     |
  |     v
  |   [Platform records feedback]
  |     |-- Stored in feedback table with tenant_id scoping (RLS)
  |     |-- Icon turns filled/highlighted (visual confirmation)
  |
  v
[Flagging check]
  |-- If 3+ users rate the SAME message_id as thumb-down:
  |     |-> Flag message for tenant admin review queue
  |     |-> POST /api/v1/admin/feedback/flags (internal)
  |
  v
End
```

### Tenant Admin Review Queue

```
Start
  |
  v
[Tenant admin navigates to Admin > Feedback]
  |
  v
[Feedback Dashboard]
  |-- Summary cards:
  |   |-- Total feedback this month: 1,240
  |   |-- Positive rate: 87%
  |   |-- Top negative tags: Inaccurate (42%), Incomplete (28%), Hallucinated (18%)
  |
  +-- Flagged Responses tab (messages with 3+ negative ratings)
  |   |-- Table: Message Preview | Negative Count | Top Tags | Status
  |   |-- Sort by: negative count (descending)
  |
  +-- All Feedback tab
  |   |-- Filterable by: rating, tags, date range, user, agent/index
  |
  v
[Click flagged response]
  |
  v
[Review Detail Panel]
  |-- Original query and response displayed
  |-- All feedback entries for this message:
  |   |-- User A: thumb-down, tags: [Inaccurate], "Wrong policy version"
  |   |-- User B: thumb-down, tags: [Hallucinated], "Made up a section"
  |   |-- User C: thumb-down, tags: [Inaccurate]
  |-- Source citations shown alongside
  |
  v
[Admin action]
  |-- Mark as "Reviewed" (acknowledged, no action needed)
  |-- Mark as "Model Issue" (response quality problem)
  |-- Mark as "Data Quality Issue" (source document outdated/incorrect)
  |-- Add admin note
  |
  v
[Aggregate analytics visible]
  |-- % positive per agent/index combination
  |-- Top negative tags per agent/index
  |-- Trend chart: feedback quality over time
  |-- Content gap detection: topics with consistently low ratings
  |
  v
End
```

### Network Effect

Positive ratings reinforce which agent/index combinations produce quality answers. Negative ratings with tags surface data quality issues to tenant admins. At the platform level (future), aggregated anonymized signals across tenants can inform model improvement and index routing optimization.

**Phase 1 deliverable**: Record feedback (rating, tags, comment), basic tenant admin feedback review panel, flagging for messages with 3+ negative ratings.

**Phase 4+ (future)**: Cross-tenant signal aggregation (anonymized, opt-in), automatic model fine-tuning based on feedback patterns, personalized response quality scoring per user.

**Error Paths**:

- Feedback API unreachable -> queue locally, retry on next interaction; icon shows "pending" state
- Duplicate feedback (user clicks twice) -> idempotent: update existing record, do not create duplicate
- Admin review queue overflows (>100 flagged) -> sort by severity (negative count), paginate

---

## Flow Summary

| Flow                 | Trigger         | Primary API                    | Key Failure Mode              |
| -------------------- | --------------- | ------------------------------ | ----------------------------- |
| First login          | Email / URL     | OAuth callback -> JWT          | SSO misconfiguration          |
| Standard chat        | User query      | POST /chat/stream (SSE)        | LLM timeout, no results       |
| Research mode        | Toggle / query  | POST /chat/stream (research)   | Too broad, timeout            |
| Document upload      | Drag-drop / btn | POST /documents/upload         | Invalid format, quota, OCR    |
| Agent delegation     | User action     | POST /agents/research/delegate | Timeout, dead end             |
| Internet fallback    | Auto-trigger    | Tavily API                     | API unavailable, low quality  |
| Conversation history | Sidebar click   | GET /conversations             | Retention expired, RBAC limit |
| Failure recovery     | Various         | Various                        | Timeout, rate limit, session  |
| Response feedback    | User action     | POST /feedback                 | API unreachable, duplicates   |

---

**Document Version**: 1.1
**Last Updated**: March 4, 2026
