# 04 — Frontend Implementation Todos

**Stack**: Next.js 14 (App Router) + TypeScript + Shadcn/UI + TanStack Table + Recharts + React Query
**Design system**: Obsidian Intelligence (dark-first)
**Ports**: Frontend 3022, Backend 8022
**API base**: `NEXT_PUBLIC_API_URL` from `.env.local`

---

## Project Setup

### FE-001: Initialize Next.js project with Obsidian Intelligence design system

**Effort**: 8h
**Depends on**: none
**Route**: N/A (project-level)
**Description**: Create the Next.js 14 App Router project at `src/web/`. Install all dependencies: Shadcn/UI (dark theme), TanStack Table, Recharts, React Query, next-auth, lucide-react, html2canvas. Configure Tailwind with Obsidian Intelligence design tokens. Set up global CSS variables, font loading, and base layout.
**Components**:

- `tailwind.config.ts` with custom colors, radii, fonts
- `app/globals.css` with CSS custom properties
- `lib/fonts.ts` — Plus Jakarta Sans (display + body) + DM Mono (data/numbers) via `next/font/google`
- `app/layout.tsx` — root layout with font classes, dark theme, QueryClientProvider
  **Acceptance criteria**:
- [ ] `--bg-base: #0C0E14` applied as body background
- [ ] `--accent: #4FFFB0` available as Tailwind color `accent`
- [ ] Border radius tokens: controls `7px`, cards `10px`, badges `4px`
- [ ] Plus Jakarta Sans renders for all body/display text
- [ ] DM Mono renders for all numeric/data content
- [ ] Shadcn/UI components render in dark theme
- [ ] `NEXT_PUBLIC_API_URL` read from `.env.local` (never hardcoded)
- [ ] TypeScript strict mode enabled, zero `any` types
      **Notes**: Use `npx create-next-app@14 src/web --typescript --tailwind --app --no-src-dir`. Follow `02-web-instructions.md` setup section exactly.

---

### FE-002: API client and auth infrastructure

**Effort**: 6h
**Depends on**: FE-001
**Route**: N/A (lib-level)
**Description**: Create the shared API client (`lib/api.ts`), auth utilities, and React Query provider. JWT stored in httpOnly cookie (not localStorage). Middleware redirects to `/login` if cookie expired. Role-based route protection via middleware checking JWT `scope` and `role` claims.
**Components**:

- `lib/api.ts` — `apiClient(path, options)` with Bearer token injection, error handling
- `lib/auth.ts` — `getToken()`, `getCurrentUser()`, role helpers
- `lib/react-query.ts` — QueryClient configuration with default stale/gc times
- `middleware.ts` — Next.js middleware for route protection by scope/role
- `app/(auth)/login/page.tsx` — login page
  **Acceptance criteria**:
- [ ] `apiClient` reads `NEXT_PUBLIC_API_URL` from env, never hardcodes URL
- [ ] 401 responses redirect to `/login`
- [ ] 403 responses show "Access Denied" page
- [ ] JWT stored in httpOnly cookie
- [ ] Middleware blocks `/platform/*` unless `scope=platform`
- [ ] Middleware blocks `/admin/*` unless `scope=tenant` + admin role
- [ ] React Query provider wraps all pages
      **Notes**: Phase 1 uses JWT auth only (no Auth0). Login via `POST /api/v1/auth/local/login`.

---

### FE-003: Shared layout shell with role-based navigation

**Effort**: 6h
**Depends on**: FE-002
**Route**: All routes
**Description**: Build the application shell with sidebar navigation, topbar, and role switcher. Sidebar shows different nav items based on JWT claims. Sidebar label for end users is "Agents" (never "Workspaces"). Topbar includes user avatar, notification bell placeholder, and role indicator.
**Components**:

- `components/layout/AppShell.tsx` — sidebar + topbar + content area
- `components/layout/Sidebar.tsx` — role-aware nav items
- `components/layout/Topbar.tsx` — user menu, notification bell slot, role badge
- `components/layout/RoleSwitcher.tsx` — dev-only role switcher (disabled in production)
  **Acceptance criteria**:
- [ ] End user sees: Chat, Agents, My Reports in sidebar
- [ ] Tenant admin sees: Dashboard, Users, Document Stores, Glossary, Agents, Analytics, Teams, Settings
- [ ] Platform admin sees: Dashboard, Tenants, LLM Profiles, Agent Templates, Tool Catalog, Cost Analytics, Issues
- [ ] Sidebar label reads "Agents" for end user view (not "Workspaces")
- [ ] Active nav item highlighted with `--accent` color
- [ ] Responsive: sidebar collapses to icon-only on mobile (375px)
- [ ] Sidebar collapses to hamburger menu on tablet (768px)
      **Notes**: Three role views share the same Next.js app. JWT claims drive visibility.

---

## Core Chat Interface (End User)

### FE-004: Chat page — empty state layout

**Effort**: 6h
**Depends on**: FE-003
**Route**: `/chat`
**Description**: Build the chat page empty state with centered input field, agent selector above the input, and knowledge base hint below. This is the default view when no conversation is active. Input is vertically and horizontally centered.
**Components**:

- `app/(user)/chat/page.tsx` — two-state orchestrator
- `app/(user)/chat/elements/EmptyState.tsx` — centered layout with input + agent selector
- `app/(user)/chat/elements/AgentSelector.tsx` — dropdown/chip selector for available agents
- `app/(user)/chat/elements/ChatInput.tsx` — message input with send button, attach file
- `app/(user)/chat/elements/KBHint.tsx` — "SharePoint . Google Drive . 2,081 documents indexed"
  **Acceptance criteria**:
- [ ] Input is centered vertically and horizontally on empty state
- [ ] Agent selector shows all agents user has access to
- [ ] KB hint shows actual document count and source names (never raw "RAG ." label)
- [ ] Pressing Enter or clicking Send transitions to active state
- [ ] Agent selector fetches from `GET /api/v1/agents` (user-scoped)
- [ ] Loading skeleton shown while agents load
- [ ] Responsive at 375px, 768px, 1024px+
      **Notes**: KB hint format canonical: "SharePoint . Google Drive . 2,081 documents indexed"

---

### FE-005: Chat page — active state layout with SSE streaming

**Effort**: 12h
**Depends on**: FE-004
**Route**: `/chat`
**Description**: Build the active chat state with message history scrolling above and input fixed at the bottom. Implement full SSE streaming for chat responses including token streaming, status indicators, source documents, confidence score, and metadata events. Handle all SSE event types from the integration guide.
**Components**:

- `app/(user)/chat/elements/ActiveChat.tsx` — message list + fixed input layout
- `app/(user)/chat/elements/MessageList.tsx` — scrollable message history
- `app/(user)/chat/elements/UserMessage.tsx` — user message bubble
- `app/(user)/chat/elements/AIMessage.tsx` — AI response with streaming, sources, feedback
- `app/(user)/chat/elements/StreamingText.tsx` — progressive text render from SSE chunks
- `app/(user)/chat/elements/StatusIndicator.tsx` — "Searching knowledge base...", "Generating response..."
- `lib/sse.ts` — SSE client for `POST /api/v1/chat/stream`
  **Acceptance criteria**:
- [ ] Input fixed at bottom, messages scroll above
- [ ] SSE `status` events show stage indicators (searching, generating)
- [ ] SSE `response_chunk` events stream text progressively
- [ ] SSE `sources` events populate source panel data
- [ ] SSE `metadata` events populate confidence score
- [ ] SSE `done` event finalizes message with conversation_id and message_id
- [ ] SSE `error` events show inline error with retry button
- [ ] Auto-scroll to bottom on new content (unless user has scrolled up)
- [ ] Message history fetched from `GET /api/v1/conversations/{id}/messages` on page load
- [ ] Loading skeleton shown while conversation loads
      **Notes**: SSE protocol defined in `03-integration-guide.md`. Use `response.body.getReader()` for streaming.

---

### FE-006: Chat — thumbs up/down feedback widget

**Effort**: 3h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Add thumbs up/down feedback buttons on every AI response message. Submits to `POST /api/v1/feedback`. Show confirmation state after submission. Only one selection per message (toggle behavior).
**Components**:

- `app/(user)/chat/elements/FeedbackWidget.tsx` — thumbs up/down buttons with state
  **Acceptance criteria**:
- [ ] Thumbs up and thumbs down buttons visible on every AI response
- [ ] Clicking submits to `POST /api/v1/feedback` with message_id and rating
- [ ] Selected state shows filled icon with accent color
- [ ] Can change selection (toggles to other option, re-submits)
- [ ] Error state shown if submission fails
- [ ] Buttons use `outlined neutral` style (not filled accent) until selected
      **Notes**: Wire to `POST /api/v1/feedback` per integration guide.

---

### FE-007: Chat — source panel slide-out

**Effort**: 6h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Build a slide-out panel that shows RAG source documents when "View Sources" is clicked on an AI response. Each source shows title, relevance score, and URL. Panel slides from right edge.
**Components**:

- `app/(user)/chat/elements/SourcePanel.tsx` — slide-out drawer from right
- `app/(user)/chat/elements/SourceCard.tsx` — individual source with title, score bar, URL
- `app/(user)/chat/elements/ViewSourcesButton.tsx` — trigger button on AI message
  **Acceptance criteria**:
- [ ] Panel slides from right with smooth animation (200ms)
- [ ] Each source card shows: title, relevance score (0-100%), source URL
- [ ] Score shown as horizontal bar with percentage label
- [ ] Clicking source title opens URL in new tab
- [ ] Panel closes on outside click or close button
- [ ] Panel is responsive (full-width on mobile, 400px on desktop)
- [ ] Sources populated from SSE `sources` event data
      **Notes**: Source scores come from the `sources` SSE event.

---

### FE-008: Chat — retrieval confidence badge and bar

**Effort**: 4h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show a "retrieval confidence" badge on each AI response. The badge uses the exact label "retrieval confidence" (canonical spec — never "answer confidence" or "AI confidence"). Includes a confidence bar visualization. Color-coded: green (>0.8), yellow (0.6-0.8), red (<0.6).
**Components**:

- `app/(user)/chat/elements/ConfidenceBadge.tsx` — labeled badge with score
- `app/(user)/chat/elements/ConfidenceBar.tsx` — horizontal bar visualization per Plan 05
  **Acceptance criteria**:
- [ ] Badge label reads exactly "retrieval confidence" (lowercase)
- [ ] Score displayed as percentage (e.g., "87%")
- [ ] Bar width proportional to score
- [ ] Color: green `#4FFFB0` for >80%, yellow `#FFD700` for 60-80%, red `#FF4F4F` for <60%
- [ ] Score populated from SSE `metadata.retrieval_confidence` field
- [ ] Badge uses `4px` border radius (badge token)
- [ ] DM Mono font for the percentage number
      **Notes**: Canonical spec from `34-rag-quality-feedback-architecture.md`. Label must be "retrieval confidence".

---

### FE-009: Chat — ProfileIndicator component

**Effort**: 3h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show a "Personalized" badge on AI responses when the `profile_context_used` SSE event is `true`. Indicates the response was influenced by the user's profile context. Badge appears inline with the confidence badge.
**Components**:

- `app/(user)/chat/elements/ProfileIndicator.tsx` — "Personalized" badge
  **Acceptance criteria**:
- [ ] Badge shows "Personalized" text with a user icon
- [ ] Only visible when SSE `profile_context_used` event is `true`
- [ ] Badge uses `4px` border radius, accent-tinted background
- [ ] Tooltip on hover: "This response was personalized using your work profile"
- [ ] Hidden when `profile_context_used` is `false` or absent
      **Notes**: Part of Plan 08 (Profile & Memory). SSE event `profile_context_used` is a boolean.

---

### FE-010: Chat — team context indicator badge

**Effort**: 2h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show "Using [Team Name] context" badge when team working memory is injected into the response. Visible in the chat message metadata area.
**Components**:

- `app/(user)/chat/elements/TeamContextBadge.tsx` — team context indicator
  **Acceptance criteria**:
- [ ] Badge shows "Using Finance Team context" (dynamic team name)
- [ ] Only visible when team memory was injected (SSE event or metadata flag)
- [ ] Uses team icon + badge styling consistent with ProfileIndicator
- [ ] Hidden when no active team or no team memory injected
      **Notes**: Part of Plan 10 (Teams Collaboration).

---

### FE-011: Chat — active team selector

**Effort**: 4h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Dropdown in the chat header that shows the current active team. Switching teams updates the session via API. Teams fetched from user's team memberships.
**Components**:

- `app/(user)/chat/elements/ActiveTeamSelector.tsx` — dropdown in chat header
  **Acceptance criteria**:
- [ ] Dropdown shows all teams user is a member of
- [ ] Current active team shown as selected
- [ ] "No team" / "Personal" option available to deselect team
- [ ] Switching team calls API to update session `active_team`
- [ ] Change takes effect on next message (no page reload needed)
- [ ] Teams fetched from `GET /api/v1/me/teams`
- [ ] Loading state while teams fetch
      **Notes**: Part of Plan 10. Active team stored in Redis session key.

---

### FE-012: Chat — "Memory saved" toast notification

**Effort**: 2h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show a toast notification when the `memory_saved` SSE event is received. Triggered when the user says "remember that..." and the system saves a memory note. Toast auto-dismisses after 4 seconds.
**Components**:

- `app/(user)/chat/elements/MemorySavedToast.tsx` — toast component
- `lib/hooks/useSSEToast.ts` — hook that listens for `memory_saved` SSE events
  **Acceptance criteria**:
- [ ] Toast shows "Memory saved" with a checkmark icon
- [ ] Appears when `memory_saved` SSE event is received
- [ ] Auto-dismisses after 4 seconds
- [ ] Stacks if multiple events arrive quickly
- [ ] Uses Shadcn toast component styled with Obsidian Intelligence theme
      **Notes**: Part of Plan 08 Sprint 6. The "remember that..." fast path triggers this.

---

### FE-013: Chat — "Terms interpreted" glossary indicator

**Effort**: 4h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show a mandatory indicator when `glossary_expansions_applied` has entries in the SSE metadata. Clicking the indicator shows a popover listing each term and its expansion. Indicator is mandatory (must be shown, not optional).
**Components**:

- `app/(user)/chat/elements/GlossaryIndicator.tsx` — clickable badge
- `app/(user)/chat/elements/GlossaryExpansionList.tsx` — popover with term/expansion pairs
  **Acceptance criteria**:
- [ ] Badge shows "X terms interpreted" (count of expansions)
- [ ] Mandatory: must be visible when `glossary_expansions_applied` is non-empty
- [ ] Clicking opens popover listing each term and its full expansion
- [ ] Popover uses card styling with `10px` border radius
- [ ] Hidden only when `glossary_expansions_applied` is empty or absent
- [ ] Each term entry shows: abbreviation -> full form + definition
      **Notes**: Glossary injection per Plan 06 Sprint B2. Max 20 terms per query.

---

### FE-014: Chat — cache state indicator

**Effort**: 3h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Show a chip on each AI response indicating whether the response came from cache or live LLM. Cache hit shows "Fast response" chip; live shows "Live response" chip. Hover tooltip shows age for cache hits.
**Components**:

- `app/(user)/chat/elements/CacheStateChip.tsx` — chip with icon and tooltip
  **Acceptance criteria**:
- [ ] Cache hit: chip shows "Fast response" with lightning icon
- [ ] Cache miss / live: chip shows "Live response" with green dot icon
- [ ] Hover tooltip for cache hit: "Response from cache (3.2 hours ago)" with age
- [ ] Cache hit chip includes "[Refresh]" link that re-queries without cache
- [ ] Data sourced from SSE `cache_state` event (hit/miss, similarity, age)
- [ ] Chip uses `4px` border radius
      **Notes**: Part of Plan 03 Phase C4. SSE `cache_state` event added in Phase C3.

---

### FE-015: Chat — conversation list sidebar

**Effort**: 5h
**Depends on**: FE-005
**Route**: `/chat`
**Description**: Conversation history list in the sidebar or left panel. Shows recent conversations with title and timestamp. Clicking loads that conversation. New conversation button at top.
**Components**:

- `app/(user)/chat/elements/ConversationList.tsx` — scrollable list of conversations
- `app/(user)/chat/elements/ConversationItem.tsx` — single conversation row
- `app/(user)/chat/elements/NewConversationButton.tsx` — creates new conversation
  **Acceptance criteria**:
- [ ] Fetches from `GET /api/v1/conversations` with pagination
- [ ] Shows conversation title (or first message preview) + relative timestamp
- [ ] Active conversation highlighted
- [ ] New conversation button resets to empty state
- [ ] Virtual scrolling if >100 conversations
- [ ] Loading skeleton while fetching
      **Notes**: Uses React Query for server state. TanStack Virtual for long lists.

---

## Settings — Privacy Page (End User, Plan 08)

### FE-016: Privacy settings page — profile learning card

**Effort**: 4h
**Depends on**: FE-003
**Route**: `/settings/privacy`
**Description**: Privacy settings page with a Profile Learning card. Contains a toggle for enabling/disabling profile learning (ON by default) and a "How does this work?" link that opens the PrivacyDisclosureDialog.
**Components**:

- `app/(user)/settings/privacy/page.tsx` — privacy settings orchestrator
- `app/(user)/settings/privacy/elements/ProfileLearningCard.tsx` — card with toggle
- `lib/hooks/usePrivacySettings.ts` — hook for privacy preference CRUD
  **Acceptance criteria**:
- [ ] Toggle labeled "Profile Learning" with ON as default
- [ ] Toggle calls API to update preference on change
- [ ] "How does this work?" link opens PrivacyDisclosureDialog
- [ ] Card uses `10px` border radius
- [ ] Loading skeleton while preference loads
      **Notes**: Toggle persists via `PATCH /api/v1/me/privacy-settings`.

---

### FE-017: PrivacyDisclosureDialog component

**Effort**: 4h
**Depends on**: FE-016
**Route**: `/settings/privacy`
**Description**: Informational dialog explaining what data is collected and why. This is a transparency disclosure (NOT a consent gate). Shows: what is collected, legitimate interest basis, right to object via the profile learning toggle. Uses Shadcn Dialog component.
**Components**:

- `components/privacy/PrivacyDisclosureDialog.tsx` — informational modal
  **Acceptance criteria**:
- [ ] Dialog title: "How Profile Learning Works"
- [ ] Content sections: "What we collect", "Why", "Your rights"
- [ ] Clearly states: legitimate interest basis (not consent)
- [ ] Points to the profile learning toggle as the opt-out mechanism
- [ ] NOT a consent gate: no "I agree" button, just "Close" / "Got it"
- [ ] Dialog uses `10px` border radius for the card
- [ ] Accessible: focus trap, escape to close, aria-labels
      **Notes**: Reframed from "ConsentDialog" to "PrivacyDisclosureDialog" per Plan 08 Sprint 7. GDPR requires opt-in for EU tenants.

---

### FE-018: Work profile card with toggles

**Effort**: 3h
**Depends on**: FE-016
**Route**: `/settings/privacy`
**Description**: Work Profile card on the privacy settings page. Master toggle: "Use my work profile to personalize responses". Sub-toggle (visible when master is ON): "Include my manager info".
**Components**:

- `app/(user)/settings/privacy/elements/WorkProfileCard.tsx` — card with master + sub toggles
  **Acceptance criteria**:
- [ ] Master toggle: "Use my work profile to personalize responses"
- [ ] Sub-toggle: "Include my manager info" (only visible when master is ON)
- [ ] Sub-toggle hidden with smooth animation when master turned OFF
- [ ] Both toggles persist via API
- [ ] Card uses `10px` border radius
      **Notes**: Org context toggles from Plan 08.

---

### FE-019: Memory notes list with CRUD

**Effort**: 6h
**Depends on**: FE-016
**Route**: `/settings/privacy`
**Description**: Memory Notes card showing all user's memory notes. Each note displays content, source badge ([saved by you] or [auto-extracted]), date, and a delete button. Includes Clear All with confirmation. Empty state with helpful text and CTA to chat.
**Components**:

- `app/(user)/settings/privacy/elements/MemoryNotesCard.tsx` — card wrapper
- `components/memory/MemoryNotesList.tsx` — reusable list component
- `components/memory/MemoryNoteItem.tsx` — single note with source badge + delete
- `lib/hooks/useUserMemory.ts` — CRUD hook for memory notes
  **Acceptance criteria**:
- [ ] Notes listed newest first
- [ ] Source badge: `[saved by you]` (user-directed) or `[auto-extracted]` (LLM-extracted)
- [ ] Each note shows: content text, source badge, relative date, delete button
- [ ] Delete button: confirm inline, then calls `DELETE /api/v1/me/memory/{id}`
- [ ] Clear All button opens confirmation dialog, then calls `DELETE /api/v1/me/memory`
- [ ] Empty state: "No memories saved. Say 'remember that...' in a chat to save a fact." + "Go to Chat" CTA
- [ ] `useUserMemory` hook exposes: `notes`, `deleteNote`, `clearAll`, `isLoading`
- [ ] Loading skeleton while notes fetch
      **Notes**: Max 15 notes per user. 200-char max per note. Part of Plan 08 Sprint 7.

---

### FE-020: Data rights section — export and clear

**Effort**: 4h
**Depends on**: FE-016
**Route**: `/settings/privacy`
**Description**: Data rights section at the bottom of privacy settings. Two actions: "Export my data" (downloads JSON) and "Clear all learning data" (with warning dialog). Clear action wipes profile, notes, and working memory.
**Components**:

- `app/(user)/settings/privacy/elements/DataRightsSection.tsx` — export + clear actions
- `app/(user)/settings/privacy/elements/ClearDataDialog.tsx` — destructive action confirmation
  **Acceptance criteria**:
- [ ] "Export my data" button triggers download of `profile_export_{timestamp}.json`
- [ ] Export calls `GET /api/v1/me/data-export` and downloads response as file
- [ ] "Clear all learning data" opens warning dialog explaining what will be deleted
- [ ] Warning dialog lists: profile data, memory notes, working memory
- [ ] Confirm button is destructive (red), requires typing "CLEAR" to confirm
- [ ] Clear calls `DELETE /api/v1/me/learning-data` then refreshes all privacy cards
- [ ] Both buttons styled as outlined (not filled) for secondary actions
      **Notes**: GDPR compliance requirement. `clear_profile_data()` must wipe all three stores.

---

## Issue Reporting (Plan 04)

### FE-021: Issue reporter floating button

**Effort**: 2h
**Depends on**: FE-003
**Route**: All pages (global)
**Description**: Floating "Report Issue" button fixed at bottom-right of viewport. Available on all pages for authenticated users. Keyboard shortcut: Ctrl+Shift+F.
**Components**:

- `components/issue-reporting/IssueReporterButton.tsx` — floating trigger button
  **Acceptance criteria**:
- [ ] Position: fixed, bottom-right, z-index 9999
- [ ] Button shows bug icon + "Report Issue" text (collapses to icon-only on mobile)
- [ ] Keyboard shortcut Ctrl+Shift+F opens the reporter dialog
- [ ] Hidden behind feature flag `FEATURE_ISSUE_REPORTING_ENABLED`
- [ ] Only shown to authenticated users
      **Notes**: Plan 04 Phase 1. Position must not overlap chat input on `/chat` page.

---

### FE-022: Issue reporter dialog with screenshot and annotation

**Effort**: 12h
**Depends on**: FE-021
**Route**: All pages (global)
**Description**: Modal dialog with issue reporting form, automatic screenshot capture via html2canvas, annotation toolbar (highlight, arrow, text, redact), and manual upload fallback. RAG response area is blurred by default in screenshot preview.
**Components**:

- `components/issue-reporting/IssueReporterDialog.tsx` — modal with form + screenshot
- `components/issue-reporting/ScreenshotCapture.ts` — html2canvas service
- `components/issue-reporting/AnnotationCanvas.tsx` — annotation toolbar (highlight, arrow, text, redact)
- `components/issue-reporting/ScreenshotPreview.tsx` — preview with blur control
- `lib/hooks/useSessionContext.ts` — captures current URL, last query, console errors
- `lib/issue-reporting/pii-redaction.ts` — PII pattern matching + redaction
- `lib/issue-reporting/offline-queue.ts` — IndexedDB offline queue
  **Acceptance criteria**:
- [ ] Form fields: title (200 char limit), description (10,000 char limit), type selector (bug/performance/ux/feature), severity hint
- [ ] Screenshot auto-captured via html2canvas on dialog open
- [ ] RAG response area blurred by default in preview; user must explicitly un-blur before upload (R4.1 CRITICAL)
- [ ] Annotation tools: highlight (yellow overlay), arrow, text label, redact (black box)
- [ ] Manual file upload fallback if html2canvas fails
- [ ] PII auto-redaction: password fields masked, email patterns detected
- [ ] Session context auto-collected: URL, last query, console errors, browser info
- [ ] Submit calls `POST /api/v1/issue-reports` with all data
- [ ] Screenshot uploaded via pre-signed URL from `GET /api/v1/issue-reports/presign`
- [ ] Offline queue: if network fails, store in IndexedDB, retry on reconnect
- [ ] Rate limit error (429) shows retry-after message
- [ ] Success state: "Report submitted" with report ID
      **Notes**: Plan 04 Phase 1. Screenshot blur is CRITICAL per R4.1 — prevents accidental leakage of sensitive RAG content.

---

### FE-023: Error detection auto-prompt

**Effort**: 3h
**Depends on**: FE-021
**Route**: All pages (global)
**Description**: Monitor for 5xx API responses. When a 5xx occurs, auto-prompt the user with a non-intrusive banner: "Something went wrong. Report this issue?" Clicking opens the pre-filled issue reporter dialog.
**Components**:

- `components/issue-reporting/ErrorDetectionBanner.tsx` — dismissible banner
- `lib/issue-reporting/error-monitor.ts` — API response interceptor
  **Acceptance criteria**:
- [ ] Banner appears within 2 seconds of a 5xx response
- [ ] Banner is dismissible (X button)
- [ ] "Report this issue" link opens IssueReporterDialog pre-filled with error context
- [ ] Does not appear more than once per 5-minute window (debounced)
- [ ] Error context auto-populated: endpoint, status code, request ID
      **Notes**: Auto-triggered reports target >=10% of error events per Plan 04.

---

### FE-024: My Reports page

**Effort**: 6h
**Depends on**: FE-003
**Route**: `/my-reports`
**Description**: User-facing list of submitted issue reports with status badges and detail view. Each report shows status timeline, AI triage result, linked GitHub issue, and SLA info. Includes "Still happening?" confirmation flow after fix notification.
**Components**:

- `app/(user)/my-reports/page.tsx` — paginated report list
- `app/(user)/my-reports/elements/ReportList.tsx` — list with status badges
- `app/(user)/my-reports/elements/ReportDetail.tsx` — detail view with timeline
- `app/(user)/my-reports/elements/StatusTimeline.tsx` — visual status progression
- `app/(user)/my-reports/elements/StillHappeningPrompt.tsx` — post-fix confirmation
  **Acceptance criteria**:
- [ ] List shows: title, type badge, severity badge, status badge, submitted date
- [ ] Status badges color-coded: received (gray), triaging (blue), in-progress (yellow), resolved (green), closed (dim)
- [ ] Detail view shows full timeline: received -> triaged -> assigned -> fix in progress -> resolved
- [ ] GitHub issue link shown if available (opens in new tab)
- [ ] "Still happening?" prompt appears after status changes to "resolved"
- [ ] Follow-up comment submission via text input
- [ ] Paginated with `GET /api/v1/my-reports`
- [ ] Loading skeleton while fetching
      **Notes**: Plan 04 Phase 3. "Still happening?" rate limit: max 1 auto-escalation per fix deployment.

---

### FE-025: Notification bell with SSE

**Effort**: 5h
**Depends on**: FE-003
**Route**: All pages (topbar)
**Description**: Notification bell icon in the topbar with unread count badge. Clicking opens a dropdown list of notifications. Real-time delivery via SSE subscription to `/api/v1/notifications/stream`. Notifications link to relevant report/page.
**Components**:

- `components/notifications/NotificationBell.tsx` — bell icon with count badge
- `components/notifications/NotificationList.tsx` — dropdown list
- `components/notifications/NotificationItem.tsx` — single notification row
- `lib/hooks/useNotifications.ts` — SSE subscription + notification state
  **Acceptance criteria**:
- [ ] Bell icon in topbar with red badge showing unread count
- [ ] Badge hidden when count is 0
- [ ] Dropdown shows recent notifications (paginated, 20 per page)
- [ ] Each notification: icon, message, relative time, read/unread indicator
- [ ] Clicking notification marks as read and navigates to relevant page
- [ ] SSE connection to `/api/v1/notifications/stream` for real-time updates
- [ ] SSE auto-reconnects on disconnect
- [ ] Notification delivery latency < 2 seconds
      **Notes**: Plan 04 Phase 3. Reused across issue reporting, sync alerts, and other notification sources.

---

## Tenant Admin Console (Plan 06)

### FE-026: Tenant admin dashboard

**Effort**: 6h
**Depends on**: FE-003
**Route**: `/admin`
**Description**: Tenant admin landing page with health summary cards, setup checklist (progresses as admin completes onboarding tasks), and quick action buttons. Shows at-a-glance workspace status.
**Components**:

- `app/(admin)/admin/page.tsx` — dashboard orchestrator
- `app/(admin)/admin/elements/HealthSummaryCards.tsx` — KPI cards (users, documents, agents, satisfaction)
- `app/(admin)/admin/elements/SetupChecklist.tsx` — onboarding progress checklist
- `app/(admin)/admin/elements/QuickActions.tsx` — common admin actions
  **Acceptance criteria**:
- [ ] KPI cards: total users, documents indexed, active agents, satisfaction rate (last 7 days)
- [ ] Each card shows value + trend indicator (up/down arrow with percentage)
- [ ] DM Mono font for all numeric values
- [ ] Setup checklist: workspace setup, auth configured, document store connected, first agent deployed, users invited
- [ ] Completed items shown with green checkmark
- [ ] Quick actions: Invite Users, Connect Document Store, Deploy Agent
- [ ] Cards use `10px` border radius
- [ ] Loading skeleton for each card independently
      **Notes**: Plan 06 Sprint A1. Data from multiple API endpoints — split into separate components per "one API call per component" rule.

---

### FE-027: User directory with invite and role management

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/users`
**Description**: User directory table with server-side pagination, sort, and filter. Supports single email invite, bulk CSV upload, inline role change dropdown, and user suspension/deletion with confirmation dialogs.
**Components**:

- `app/(admin)/admin/users/page.tsx` — orchestrator
- `app/(admin)/admin/users/elements/UserTable.tsx` — TanStack Table with server-side pagination
- `app/(admin)/admin/users/elements/UserInviteModal.tsx` — single invite + bulk CSV
- `app/(admin)/admin/users/elements/RoleChangeDropdown.tsx` — inline role selector
- `app/(admin)/admin/users/elements/UserActionMenu.tsx` — suspend/delete actions
- `app/(admin)/admin/users/elements/SuspendUserDialog.tsx` — confirmation dialog
- `app/(admin)/admin/users/elements/DeleteUserDialog.tsx` — destructive confirmation
- `app/(admin)/admin/users/elements/BulkCSVUpload.tsx` — CSV file upload with preview
  **Acceptance criteria**:
- [ ] Table columns: name, email, role, status (active/suspended), last login
- [ ] Server-side pagination via `GET /api/v1/users?page=1&per_page=20`
- [ ] Sort by name, email, role, last login
- [ ] Filter by role, status
- [ ] Search by name or email
- [ ] Invite modal: email field + role selector + send button
- [ ] Bulk invite: CSV upload with preview table showing parsed rows + validation errors
- [ ] Role change: inline dropdown, confirmation tooltip, calls `PATCH /api/v1/users/{id}/role`
- [ ] Suspend: confirmation dialog, calls `PATCH /api/v1/users/{id}/status`
- [ ] Delete: destructive dialog with "This will anonymize all conversations", calls `DELETE /api/v1/users/{id}`
- [ ] Loading skeleton for table
- [ ] Empty state: "No users yet. Invite your first team member."
      **Notes**: Plan 06 Sprint A1. TanStack Table with server-side pagination per `02-web-instructions.md`.

---

### FE-028: Workspace settings page

**Effort**: 4h
**Depends on**: FE-003
**Route**: `/admin/settings`
**Description**: Workspace settings form: display name, logo upload (drag-and-drop + file picker), timezone selector, locale selector, notification preferences.
**Components**:

- `app/(admin)/admin/settings/page.tsx` — settings form
- `app/(admin)/admin/settings/elements/LogoUpload.tsx` — drag-and-drop + file picker
- `app/(admin)/admin/settings/elements/TimezoneSelector.tsx` — searchable timezone dropdown
  **Acceptance criteria**:
- [ ] Display name: text input with 100-char limit
- [ ] Logo: drag-and-drop zone with preview, accepts PNG/SVG/JPEG, max 2MB
- [ ] Timezone: searchable dropdown with all IANA timezones
- [ ] Locale: dropdown with supported locales
- [ ] Save button calls `PATCH /api/v1/workspace`
- [ ] Success toast on save
- [ ] Form populated from `GET /api/v1/workspace`
- [ ] Unsaved changes warning on navigate away
      **Notes**: Plan 06 Sprint A1.

---

### FE-029: Document store list and SharePoint wizard

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/document-stores`
**Description**: List of connected document sources with status cards. SharePoint connection wizard: multi-step guided flow with permission instructions (screenshots), credential entry, connection test, and site selector.
**Components**:

- `app/(admin)/admin/document-stores/page.tsx` — source list orchestrator
- `app/(admin)/admin/document-stores/elements/SourceStatusCard.tsx` — per-source status card
- `app/(admin)/admin/document-stores/elements/SharePointWizard.tsx` — multi-step wizard
- `app/(admin)/admin/document-stores/elements/PermissionInstructions.tsx` — step-by-step Azure instructions with screenshots
- `app/(admin)/admin/document-stores/elements/CredentialEntryForm.tsx` — client ID/secret entry
- `app/(admin)/admin/document-stores/elements/ConnectionTest.tsx` — test connection with loading/success/failure states
- `app/(admin)/admin/document-stores/elements/SiteSelector.tsx` — multi-select site list
  **Acceptance criteria**:
- [ ] Source list shows all connected sources with status card each
- [ ] Status card: source name, document count, last sync time, error count, "Sync Now" button
- [ ] "Sync Now" calls `POST /api/v1/sync/trigger` and shows progress
- [ ] SharePoint wizard steps: 1) Permission instructions, 2) Credential entry, 3) Connection test, 4) Site selector
- [ ] Permission instructions include numbered steps with Azure portal screenshots/mockups
- [ ] Connection test shows spinner -> success (green check) or failure (red X with error message)
- [ ] Site selector: multi-select checkboxes of discovered SharePoint sites
- [ ] Wizard state preserved (can go back/forward)
- [ ] Credentials never shown after initial entry (masked)
      **Notes**: Plan 06 Sprint A2. Credential management per section 4.4 of tenant admin plan.

---

### FE-030: Google Drive wizard

**Effort**: 6h
**Depends on**: FE-029
**Route**: `/admin/document-stores`
**Description**: Google Drive connection wizard with two paths: OAuth (button click) and DWD (JSON file upload + sync user entry). Includes folder tree selector after connection.
**Components**:

- `app/(admin)/admin/document-stores/elements/GoogleDriveWizard.tsx` — dual-path wizard
- `app/(admin)/admin/document-stores/elements/OAuthConnectButton.tsx` — OAuth initiation
- `app/(admin)/admin/document-stores/elements/DWDSetupForm.tsx` — JSON upload + sync user
- `app/(admin)/admin/document-stores/elements/FolderTreeSelector.tsx` — folder tree view
  **Acceptance criteria**:
- [ ] Two paths presented: "Connect with Google Sign-In" (OAuth) and "Domain-Wide Delegation" (DWD)
- [ ] OAuth: button initiates `POST /api/v1/integrations/googledrive/auth` and handles redirect
- [ ] DWD: JSON file upload for service account + text input for sync user email
- [ ] DWD note: sync user must be a real Workspace user (not SA email)
- [ ] Folder tree: expandable tree view of drives/folders with checkboxes
- [ ] Connection test after either path
- [ ] Error states with clear fix suggestions
      **Notes**: Plan 06 Sprint A2. DWD requires Workspace Super Admin (per risk R02).

---

### FE-031: Sync failure list

**Effort**: 4h
**Depends on**: FE-029
**Route**: `/admin/document-stores`
**Description**: Per-source list of sync failures. Each failure shows filename, error description, system-generated fix suggestion, and "Add to exclusion list" action.
**Components**:

- `app/(admin)/admin/document-stores/elements/SyncFailureList.tsx` — paginated failure list
- `app/(admin)/admin/document-stores/elements/SyncFailureItem.tsx` — individual failure row
  **Acceptance criteria**:
- [ ] Each failure shows: filename, error message, fix suggestion (system-generated)
- [ ] "Add to exclusion list" button per failure (excludes file from future syncs)
- [ ] Fix suggestions are actionable (e.g., "Grant read permission to the service account for this file")
- [ ] No raw API errors shown to admin (always human-readable)
- [ ] Fetched from `GET /api/v1/sync/status` failure list
- [ ] Paginated for sources with many failures
      **Notes**: Plan 06 Sprint A2. Sync failure diagnosis accuracy target >80%.

---

### FE-032: SSO configuration wizard (SAML + OIDC)

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/sso`
**Description**: SSO configuration page with two wizard paths: SAML 2.0 and OIDC. SAML: SP metadata download, IdP metadata upload, attribute mapping table, test login. OIDC: client credentials, auto-discovery URL, test. Both include enable/disable toggle with user impact warning.
**Components**:

- `app/(admin)/admin/sso/page.tsx` — SSO configuration orchestrator
- `app/(admin)/admin/sso/elements/SAMLWizard.tsx` — SAML setup wizard
- `app/(admin)/admin/sso/elements/OIDCWizard.tsx` — OIDC setup wizard
- `app/(admin)/admin/sso/elements/SPMetadataDownload.tsx` — download SP metadata XML
- `app/(admin)/admin/sso/elements/IdPMetadataUpload.tsx` — upload IdP metadata
- `app/(admin)/admin/sso/elements/AttributeMappingTable.tsx` — editable mapping table
- `app/(admin)/admin/sso/elements/GroupRoleMappingTable.tsx` — IdP group -> mingai role mapping
- `app/(admin)/admin/sso/elements/TestLoginButton.tsx` — test SSO login flow
- `app/(admin)/admin/sso/elements/SSOToggle.tsx` — enable/disable with warning
  **Acceptance criteria**:
- [ ] SAML wizard: 4 steps (download SP metadata, upload IdP metadata, map attributes, test login)
- [ ] OIDC wizard: 3 steps (enter client credentials + discovery URL, configure, test)
- [ ] SP metadata: download button generates XML file
- [ ] IdP metadata: file upload with XML validation
- [ ] Attribute mapping: editable table mapping IdP attributes to mingai fields
- [ ] Group-to-role mapping: add/edit/delete rows mapping IdP group names to mingai roles
- [ ] Test login: opens popup window for SSO test, shows success/failure result
- [ ] Enable/disable toggle: warning dialog about user impact before enabling
- [ ] SSO disable: keeps email/password as override (per risk R04)
      **Notes**: Plan 06 Sprint B1. SSO setup target < 2 hours.

---

### FE-033: Glossary management page

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/glossary`
**Description**: Glossary term management with CRUD, search, filter, bulk import/export, version history, and miss signals panel. Terms have 200-char definition limit with character counter.
**Components**:

- `app/(admin)/admin/glossary/page.tsx` — glossary orchestrator
- `app/(admin)/admin/glossary/elements/TermList.tsx` — searchable, filterable list
- `app/(admin)/admin/glossary/elements/TermForm.tsx` — add/edit form with character counter
- `app/(admin)/admin/glossary/elements/BulkImportDialog.tsx` — CSV upload, preview, conflict resolution
- `app/(admin)/admin/glossary/elements/VersionHistoryDrawer.tsx` — per-term edit history with rollback
- `app/(admin)/admin/glossary/elements/MissSignalsPanel.tsx` — top uncovered terms from queries
  **Acceptance criteria**:
- [ ] Term list: searchable by term/definition, filterable by active/inactive
- [ ] Term form fields: term, full form, definition (200 char limit), context tags, scope
- [ ] Character counter on definition field: warning at 180 chars, block at 200 chars
- [ ] Character counter uses DM Mono font
- [ ] Bulk import: CSV upload -> preview table -> conflict resolution (skip/overwrite/rename) -> import
- [ ] Bulk export: CSV download of all terms
- [ ] Version history: per-term drawer showing edit history with rollback button
- [ ] Miss signals panel: top terms appearing in queries without glossary coverage
- [ ] Each action persists immediately via API
- [ ] Empty state: "No glossary terms yet. Add your first term or import from CSV."
      **Notes**: Plan 06 Sprint B2. Canonical spec: max 20 terms injected, 200 chars/def, 800-token ceiling.

---

### FE-034: Sync health dashboard

**Effort**: 6h
**Depends on**: FE-029
**Route**: `/admin/sync`
**Description**: Sync health monitoring dashboard with per-source status cards, freshness indicators, schedule configuration, re-index with cost estimate, and credential expiry warnings.
**Components**:

- `app/(admin)/admin/sync/page.tsx` — sync dashboard orchestrator
- `app/(admin)/admin/sync/elements/SourceHealthCard.tsx` — per-source card with freshness indicator
- `app/(admin)/admin/sync/elements/FreshnessIndicator.tsx` — green/yellow/red dot with label
- `app/(admin)/admin/sync/elements/ScheduleConfig.tsx` — frequency selector per source
- `app/(admin)/admin/sync/elements/ReindexButton.tsx` — re-index with cost estimate dialog
- `app/(admin)/admin/sync/elements/CredentialExpiryBanner.tsx` — 30-day warning banner
  **Acceptance criteria**:
- [ ] Per-source status card: name, document count, last sync time, error count, freshness dot
- [ ] Freshness: green (<24h), yellow (24-72h), red (>72h since last successful sync)
- [ ] Schedule configuration: frequency selector (hourly, every 6h, daily, weekly) per source
- [ ] Re-index button: shows estimated embedding cost dialog before confirming
- [ ] Cost estimate uses DM Mono font for dollar amounts
- [ ] Credential expiry banner: appears 30 days before expiry, links to reconnect wizard
- [ ] Sync Now button per source
      **Notes**: Plan 06 Sprint B3.

---

### FE-035: Agent library browser

**Effort**: 8h
**Depends on**: FE-003
**Route**: `/admin/agents`
**Description**: Agent library browser with category filters, satisfaction score sort, template preview, and deployment form. Seed templates visible immediately without platform admin action.
**Components**:

- `app/(admin)/admin/agents/page.tsx` — agent library orchestrator
- `app/(admin)/admin/agents/elements/AgentGrid.tsx` — card grid with filters
- `app/(admin)/admin/agents/elements/AgentFilterBar.tsx` — category, satisfaction, tier filters
- `app/(admin)/admin/agents/elements/AgentCard.tsx` — name, description, trust score, example preview
- `app/(admin)/admin/agents/elements/TemplatePreviewModal.tsx` — read-only system prompt, variables, examples
- `app/(admin)/admin/agents/elements/AgentDeployForm.tsx` — fill variables, set name, select KBs, access control
- `app/(admin)/admin/agents/elements/UpgradeNotificationBanner.tsx` — new template version available
  **Acceptance criteria**:
- [ ] Card grid shows all available templates (seed + platform-published)
- [ ] Seed templates (HR, IT Helpdesk, Procurement, Onboarding) visible immediately
- [ ] Filter by category, satisfaction score range, plan tier
- [ ] Filter chips use outlined neutral style (NOT filled accent)
- [ ] Template preview: read-only system prompt, variable list, example conversations
- [ ] Deploy form: fill required variables, set agent name, select KBs, set access control
- [ ] KB selector: multi-select from workspace KBs with grounded/extended toggle
- [ ] Access control: workspace-wide / role-restricted / user-specific
- [ ] Upgrade notification banner when new template version available
- [ ] Loading skeleton for card grid
      **Notes**: Plan 06 Sprint C1. Seed templates shipped in codebase per R27 fix.

---

### FE-036: Agent Studio page

**Effort**: 14h
**Depends on**: FE-035
**Route**: `/admin/agents/studio`
**Description**: Full agent authoring studio with system prompt editor, AI-assisted improvement, example conversation builder, KB attachment, tool enablement, guardrail configuration, embedded test chat, and lifecycle controls.
**Components**:

- `app/(admin)/admin/agents/studio/page.tsx` — studio orchestrator
- `app/(admin)/admin/agents/studio/elements/PromptEditor.tsx` — large textarea with `{{variable}}` syntax highlighting
- `app/(admin)/admin/agents/studio/elements/AIPromptSuggestions.tsx` — inline improvement suggestions
- `app/(admin)/admin/agents/studio/elements/ExampleConversationBuilder.tsx` — add up to 5 Q&A pairs
- `app/(admin)/admin/agents/studio/elements/KBAttachment.tsx` — multi-select KB with grounded/extended toggle
- `app/(admin)/admin/agents/studio/elements/ToolEnablement.tsx` — select tools from catalog
- `app/(admin)/admin/agents/studio/elements/GuardrailConfig.tsx` — blocked topics, confidence threshold, max length
- `app/(admin)/admin/agents/studio/elements/AgentTestChat.tsx` — embedded test chat with "Show sources" toggle
- `app/(admin)/admin/agents/studio/elements/LifecycleControls.tsx` — Save Draft / Publish / Unpublish
- `app/(admin)/admin/agents/studio/elements/AgentDuplicateButton.tsx` — clone agent as starting point
  **Acceptance criteria**:
- [ ] System prompt editor: large textarea with `{{variable}}` syntax highlighted in accent color
- [ ] Variables auto-detected from `{{...}}` patterns and listed in sidebar
- [ ] AI-assisted suggestions: "Improve this prompt" button with inline diff suggestions
- [ ] Example conversations: up to 5 Q&A pairs with add/remove
- [ ] KB attachment: multi-select dropdown from workspace KBs, grounded/extended toggle per KB
- [ ] Tool enablement: checkbox list from platform catalog (Professional+ plan only, grayed out otherwise)
- [ ] Guardrail config: blocked topic tags, confidence threshold slider (0-100), max response length
- [ ] Test chat: embedded chat panel with "Show sources" toggle and confidence score display
- [ ] Lifecycle: Save as Draft, Publish (with confirmation), Unpublish
- [ ] Duplicate: clones agent config as new draft
- [ ] Unsaved changes warning on navigate away
      **Notes**: Plan 06 Sprint C2. Gated on persona validation (5-10 customer interviews first per Plan 06).

---

### FE-037: Feedback monitoring dashboard

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/analytics`
**Description**: Satisfaction dashboard with 7-day rolling rate gauge, per-agent breakdown table with sparklines, low-confidence response list, root cause correlation panel, and issue queue with response workflow.
**Components**:

- `app/(admin)/admin/analytics/page.tsx` — analytics orchestrator
- `app/(admin)/admin/analytics/elements/SatisfactionGauge.tsx` — 7-day rolling rate gauge (Recharts)
- `app/(admin)/admin/analytics/elements/SatisfactionTrend.tsx` — trend chart (Recharts area chart)
- `app/(admin)/admin/analytics/elements/AgentBreakdownTable.tsx` — per-agent with sparklines
- `app/(admin)/admin/analytics/elements/LowConfidenceList.tsx` — low-confidence responses
- `app/(admin)/admin/analytics/elements/RootCausePanel.tsx` — sync freshness -> satisfaction correlation
- `app/(admin)/admin/analytics/elements/IssueQueue.tsx` — tenant-level issue list
- `app/(admin)/admin/analytics/elements/IssueResponseWorkflow.tsx` — respond, resolve, escalate actions
  **Acceptance criteria**:
- [ ] Gauge shows 7-day rolling satisfaction percentage (Recharts radial chart)
- [ ] Trend chart: 30-day area chart of daily satisfaction rate
- [ ] Agent breakdown table: agent name, satisfaction %, total ratings, 7-day sparkline
- [ ] Table sortable by satisfaction %, total ratings
- [ ] Low-confidence list: responses with retrieval_confidence < 0.6, expandable with query text
- [ ] Root cause panel: correlates sync freshness drops with satisfaction drops (timestamp comparison)
- [ ] Issue queue: reports from platform admin + tenant-config issues
- [ ] Issue actions: respond to reporter, resolve with note, escalate to platform
- [ ] Empty analytics state: "Not enough data. Analytics available after 50 rated responses."
- [ ] All numeric values in DM Mono font
- [ ] Loading skeleton per section
      **Notes**: Plan 06 Sprint C3. Cold start: R09 mitigation — explicit "not enough data" state.

---

### FE-038: Onboarding wizard (6-step)

**Effort**: 10h
**Depends on**: FE-026
**Route**: `/admin/onboarding`
**Description**: Full 6-step guided onboarding wizard: workspace setup, auth mode, LLM profile, document store, agents, users. Progress persisted (resumable). Contextual help tooltips throughout. Completion celebration.
**Components**:

- `app/(admin)/admin/onboarding/page.tsx` — wizard orchestrator
- `app/(admin)/admin/onboarding/elements/WizardProgress.tsx` — step indicator bar
- `app/(admin)/admin/onboarding/elements/WorkspaceStep.tsx` — name, logo, timezone
- `app/(admin)/admin/onboarding/elements/AuthStep.tsx` — auth mode selection
- `app/(admin)/admin/onboarding/elements/LLMProfileStep.tsx` — profile selector
- `app/(admin)/admin/onboarding/elements/DocumentStoreStep.tsx` — connect first source
- `app/(admin)/admin/onboarding/elements/AgentStep.tsx` — deploy first agent
- `app/(admin)/admin/onboarding/elements/UsersStep.tsx` — invite first users
- `app/(admin)/admin/onboarding/elements/CompletionCelebration.tsx` — success state
  **Acceptance criteria**:
- [ ] 6 steps with progress bar showing current position
- [ ] Each step can be completed or skipped (with warning)
- [ ] Progress saved to API (resumable if browser closed)
- [ ] Back/Next navigation between steps
- [ ] Contextual help tooltips: "Why do I need this?" on each section
- [ ] Completion celebration: "Your AI workspace is ready!" with confetti animation
- [ ] Redirects to dashboard after completion
- [ ] First-time admin auto-redirected to onboarding if not completed
      **Notes**: Plan 06 Sprint D1. Target: non-technical admin completes in < 4 hours.

---

## Teams Management (Tenant Admin, Plan 10)

### FE-039: Teams management page

**Effort**: 10h
**Depends on**: FE-003
**Route**: `/admin/teams`
**Description**: Teams management page for tenant admin. Team list with source badges (manual/synced), create/edit/delete forms, member management, Auth0 sync settings with allowlist, team working memory controls, and membership audit log.
**Components**:

- `app/(admin)/admin/teams/page.tsx` — teams orchestrator
- `app/(admin)/admin/teams/elements/TeamList.tsx` — team list with source badges
- `app/(admin)/admin/teams/elements/TeamForm.tsx` — create/edit team dialog
- `app/(admin)/admin/teams/elements/TeamMembersList.tsx` — member list with add/remove
- `app/(admin)/admin/teams/elements/BulkAddMembers.tsx` — bulk add from user list
- `app/(admin)/admin/teams/elements/Auth0SyncSettings.tsx` — allowlist configuration
- `app/(admin)/admin/teams/elements/TeamMemoryControls.tsx` — TTL slider, enable/disable
- `app/(admin)/admin/teams/elements/MembershipAuditLog.tsx` — actor, source, timestamp, action log
  **Acceptance criteria**:
- [ ] Team list shows: name, member count, source badge (manual/synced), status
- [ ] Source badge: `[Manual]` for admin-created, `[Auth0 Sync]` for auto-synced
- [ ] Create team: name, description
- [ ] Edit team: name, description, archive/delete
- [ ] Members list: shows all members with role, add/remove individual, bulk add
- [ ] Bulk add: multi-select from user directory
- [ ] Auth0 sync settings: allowlist of group name strings + wildcard patterns
- [ ] Default allowlist: empty (no auto-sync until configured)
- [ ] Team working memory controls: enable/disable toggle, TTL slider (1-30 days)
- [ ] Membership audit log tab: actor, source (manual/auth0_sync), timestamp, action (added/removed)
- [ ] API endpoints: `GET/POST/PUT/DELETE /api/v1/admin/teams` and `/admin/teams/{id}/members`
      **Notes**: Plan 10. Anonymous team memory attribution — no user IDs visible in team memory.

---

## Platform Admin Portal (Plan 05)

### FE-040: Platform admin dashboard

**Effort**: 8h
**Depends on**: FE-003
**Route**: `/platform`
**Description**: Platform admin landing page with KPI cards (active tenants, at-risk count, platform satisfaction, open P0/P1 issues), tenant health table ranked by score, and alert summaries.
**Components**:

- `app/(platform)/platform/page.tsx` — dashboard orchestrator
- `app/(platform)/platform/elements/PlatformKPICards.tsx` — 4 KPI cards
- `app/(platform)/platform/elements/TenantHealthTable.tsx` — ranked by health score
- `app/(platform)/platform/elements/AlertSummary.tsx` — recent alerts
- `app/(platform)/platform/elements/AtRiskBadge.tsx` — at-risk tenant indicator
  **Acceptance criteria**:
- [ ] KPI cards: active tenant count, at-risk count (red), platform satisfaction %, open P0/P1 issues
- [ ] All numeric values in DM Mono font
- [ ] Tenant health table: name, plan, status badge, health score (color-coded), cost, at-risk badge
- [ ] Health score colors: green (>70), yellow (40-70), red (<40)
- [ ] Table sortable by health score, plan, cost
- [ ] At-risk badge: "At Risk" in red when health declining 3+ consecutive weeks or score < 40
- [ ] Alert summary: last 5 alerts (quota warnings, health degradations, cost spikes)
- [ ] Loading skeleton per section
      **Notes**: Plan 05 Sprint B2. Health score calculated nightly per section 4.3 of platform admin plan.

---

### FE-041: Tenant list and provisioning wizard

**Effort**: 10h
**Depends on**: FE-040
**Route**: `/platform/tenants`
**Description**: Tenant management list with filter/sort and "New Tenant" provisioning wizard. Wizard: 4 steps (Basic Info, LLM Profile, Quotas, Review & Provision). Provisioning shows real-time progress via SSE.
**Components**:

- `app/(platform)/platform/tenants/page.tsx` — tenant list orchestrator
- `app/(platform)/platform/tenants/elements/TenantTable.tsx` — TanStack Table with server-side pagination
- `app/(platform)/platform/tenants/elements/TenantFilters.tsx` — filter by plan, status, health
- `app/(platform)/platform/tenants/elements/ProvisioningWizard.tsx` — 4-step wizard
- `app/(platform)/platform/tenants/elements/BasicInfoStep.tsx` — name, contact email, plan tier
- `app/(platform)/platform/tenants/elements/LLMProfileStep.tsx` — select from published profiles
- `app/(platform)/platform/tenants/elements/QuotaStep.tsx` — monthly token limit, rate limit
- `app/(platform)/platform/tenants/elements/ReviewStep.tsx` — summary + provision button
- `app/(platform)/platform/tenants/elements/ProvisioningProgress.tsx` — SSE real-time progress
  **Acceptance criteria**:
- [ ] Tenant table: name, plan, status badge, health score, cost, creation date, actions
- [ ] Actions: View, Suspend, Delete
- [ ] Filter by plan (Starter/Professional/Enterprise), status (active/suspended/provisioning)
- [ ] Sort by name, creation date, plan, health
- [ ] Server-side pagination via `GET /api/v1/admin/tenants`
- [ ] Provisioning wizard: 4 steps with back/next
- [ ] LLM profile step: fetches from `GET /api/v1/admin/llm-profiles`
- [ ] Review step: summary of all inputs with edit links back to each step
- [ ] Provision button: calls `POST /api/v1/admin/tenants`, returns job_id
- [ ] Provisioning progress: SSE to `/api/v1/admin/provisioning/{job_id}` showing step-by-step progress
- [ ] Progress steps: Database, Search Index, Object Store, Redis, Invite Email — each shows pending/success/failure
- [ ] Failure state: retry button per failed step
- [ ] SLA: < 10 minutes total provisioning time
      **Notes**: Plan 05 Sprint A1. Provisioning architecture per section 4.5.

---

### FE-042: Tenant detail page with health breakdown

**Effort**: 8h
**Depends on**: FE-041
**Route**: `/platform/tenants/{id}`
**Description**: Tenant detail page with status, plan info, health score breakdown (4 components with trend sparklines), cost analytics, LLM profile assignment, and suspend/reactivate/delete controls.
**Components**:

- `app/(platform)/platform/tenants/[id]/page.tsx` — detail orchestrator
- `app/(platform)/platform/tenants/[id]/elements/TenantHeader.tsx` — name, status, plan, contact
- `app/(platform)/platform/tenants/[id]/elements/HealthBreakdown.tsx` — 4 score components with sparklines
- `app/(platform)/platform/tenants/[id]/elements/CostBreakdown.tsx` — token cost, infrastructure estimate, margin
- `app/(platform)/platform/tenants/[id]/elements/LLMProfileAssignment.tsx` — current profile + change selector
- `app/(platform)/platform/tenants/[id]/elements/QuotaUsageBar.tsx` — quota consumed vs limit
- `app/(platform)/platform/tenants/[id]/elements/TenantActions.tsx` — suspend/reactivate/schedule deletion
  **Acceptance criteria**:
- [ ] Header: tenant name, status badge, plan tier, primary contact email, creation date
- [ ] Health breakdown: usage trend (30%), feature breadth (20%), satisfaction (35%), error rate (15%)
- [ ] Each component: current value, weight, 30-day sparkline (Recharts)
- [ ] Cost: tokens consumed this month, cost/token, total LLM cost, infrastructure estimate, gross margin %
- [ ] Cost values in DM Mono font, dollar amounts formatted
- [ ] LLM profile: current assignment with change button (dropdown of published profiles)
- [ ] Profile change propagates within 60 seconds (shown in UI as note)
- [ ] Quota bar: visual bar showing tokens_used / tokens_limit
- [ ] Suspend: confirmation dialog, calls `PATCH /api/v1/admin/tenants/{id}/status`
- [ ] Schedule deletion: 30-day grace period countdown
      **Notes**: Plan 05 Sprint B2. Health score algorithm per section 4.3.

---

### FE-043: LLM profile library management

**Effort**: 8h
**Depends on**: FE-040
**Route**: `/platform/llm-profiles`
**Description**: LLM profile library with create/edit form, model slot configuration (6 slots), test harness, and lifecycle management (Draft/Published/Deprecated).
**Components**:

- `app/(platform)/platform/llm-profiles/page.tsx` — profile list orchestrator
- `app/(platform)/platform/llm-profiles/elements/ProfileList.tsx` — list with status badges
- `app/(platform)/platform/llm-profiles/elements/ProfileForm.tsx` — create/edit form
- `app/(platform)/platform/llm-profiles/elements/ModelSlotConfig.tsx` — per-slot configuration
- `app/(platform)/platform/llm-profiles/elements/ProfileTestHarness.tsx` — test 3 queries against draft
- `app/(platform)/platform/llm-profiles/elements/ProfileLifecycle.tsx` — Draft/Published/Deprecated controls
  **Acceptance criteria**:
- [ ] Profile list: name, description, status badge, assigned tenant count, actions
- [ ] Create/edit form: name, description, 6 model slots (primary, intent, embedding, etc.)
- [ ] Per-slot: model selector (from available models), context window, cost tier
- [ ] Model names read from API (never hardcoded in UI)
- [ ] Test harness: run 3 test queries, view response + latency + token count + estimated cost
- [ ] Lifecycle controls: Save as Draft, Publish, Deprecate
- [ ] Deprecated profiles: shown with strikethrough, cannot be newly assigned
- [ ] Best practices notes: markdown editor per profile (visible to tenant admins)
- [ ] Cost estimate per query shown in DM Mono font
      **Notes**: Plan 05 Sprint B1. Model names always from API/env, never hardcoded.

---

### FE-044: Agent template library management

**Effort**: 8h
**Depends on**: FE-040
**Route**: `/platform/agent-templates`
**Description**: Platform admin template library for creating, versioning, and publishing agent templates. Includes template authoring form, variable definition, guardrail config, test harness, and version management.
**Components**:

- `app/(platform)/platform/agent-templates/page.tsx` — template list
- `app/(platform)/platform/agent-templates/elements/TemplateList.tsx` — list with version, performance
- `app/(platform)/platform/agent-templates/elements/TemplateAuthoringForm.tsx` — system prompt, variables, guardrails
- `app/(platform)/platform/agent-templates/elements/VariableDefinitions.tsx` — variable name, type, description, required
- `app/(platform)/platform/agent-templates/elements/TemplateTestHarness.tsx` — test against scenarios
- `app/(platform)/platform/agent-templates/elements/VersionHistory.tsx` — version list with changelog
- `app/(platform)/platform/agent-templates/elements/TemplateAnalytics.tsx` — cross-tenant performance
  **Acceptance criteria**:
- [ ] Template list: name, category, current version, status, satisfaction rate, tenant adoption count
- [ ] Authoring form: name, category, system prompt with `{{variable}}` highlighting, guardrails
- [ ] Variable definitions: name, type (text/number/select), description, required/optional, example
- [ ] Guardrail config: blocked topics, confidence threshold, required elements
- [ ] Test harness: run test scenarios against draft, review responses
- [ ] Version management: v1, v2, v3 with changelog; published versions immutable
- [ ] Analytics: per-template satisfaction rate across all tenants, guardrail trigger rate
- [ ] Publish pushes "upgrade available" notification to tenant admins
      **Notes**: Plan 05 Sprint C2.

---

### FE-045: Tool catalog management

**Effort**: 8h
**Depends on**: FE-040
**Route**: `/platform/tool-catalog`
**Description**: MCP tool registration and monitoring. Registration form, safety classification, automated health check, continuous health monitoring display, and tenant-facing catalog browser.
**Components**:

- `app/(platform)/platform/tool-catalog/page.tsx` — catalog orchestrator
- `app/(platform)/platform/tool-catalog/elements/ToolList.tsx` — list with health status
- `app/(platform)/platform/tool-catalog/elements/ToolRegistrationForm.tsx` — full registration form
- `app/(platform)/platform/tool-catalog/elements/SafetyClassificationBadge.tsx` — Read-Only/Write/Destructive
- `app/(platform)/platform/tool-catalog/elements/ToolHealthMonitor.tsx` — health status with history
- `app/(platform)/platform/tool-catalog/elements/ToolUsageAnalytics.tsx` — invocation frequency, latency, errors
- `app/(platform)/platform/tool-catalog/elements/ToolRetirementFlow.tsx` — deprecation controls
  **Acceptance criteria**:
- [ ] Tool list: name, provider, safety classification badge, health status dot, last ping
- [ ] Registration form: name, MCP endpoint (HTTPS only), auth type, capabilities, safety class
- [ ] Safety classification: Read-Only (green), Write (yellow), Destructive (red) — immutable once set
- [ ] Automated health check on registration: shows pass/fail for endpoint, auth, schema, sample invocation
- [ ] Health monitoring: green (healthy), yellow (degraded, 3+ failures), red (unavailable, 10+ failures)
- [ ] Health history: 24-hour timeline showing status transitions
- [ ] Usage analytics: invocation count, p50/p99 latency, error rate per tool per tenant
- [ ] Retirement flow: mark deprecated, notify affected tenant admins, mark discontinued
      **Notes**: Plan 05 Sprint D1.

---

### FE-046: Cross-tenant cost analytics dashboard

**Effort**: 8h
**Depends on**: FE-040
**Route**: `/platform/analytics/cost`
**Description**: Platform-level cost analytics with period selector, total platform cost, per-tenant breakdown with gross margin, and cost alert thresholds.
**Components**:

- `app/(platform)/platform/analytics/cost/page.tsx` — cost analytics orchestrator
- `app/(platform)/platform/analytics/cost/elements/PeriodSelector.tsx` — date range picker
- `app/(platform)/platform/analytics/cost/elements/PlatformCostSummary.tsx` — total cost KPI cards
- `app/(platform)/platform/analytics/cost/elements/TenantCostTable.tsx` — per-tenant breakdown
- `app/(platform)/platform/analytics/cost/elements/MarginChart.tsx` — gross margin trend (Recharts)
- `app/(platform)/platform/analytics/cost/elements/CostAlertConfig.tsx` — alert threshold settings
- `app/(platform)/platform/analytics/cost/elements/BillingReconciliationExport.tsx` — CSV export
  **Acceptance criteria**:
- [ ] Period selector: last 7 days, last 30 days, last 90 days, custom range
- [ ] Summary cards: total LLM cost, total infrastructure cost, total revenue, platform gross margin %
- [ ] Per-tenant table: name, plan, tokens consumed, LLM cost, infrastructure cost, plan revenue, gross margin %
- [ ] Margin column color-coded: green (>50%), yellow (20-50%), red (<20%)
- [ ] Margin trend chart: 30-day line chart of daily gross margin
- [ ] All dollar amounts in DM Mono font with proper formatting
- [ ] Cost alerts: configurable threshold per tenant (margin below X%)
- [ ] CSV export: per-tenant cost data for billing reconciliation
- [ ] Infrastructure costs labeled "estimated" with timestamp (24-48h delay from cloud provider)
      **Notes**: Plan 05 Sprint B3. LLM cost constants from env config (never hardcoded).

---

### FE-047: Platform issue queue

**Effort**: 8h
**Depends on**: FE-040
**Route**: `/platform/issues`
**Description**: Platform-level issue queue consuming from AI triage agent. Shows sorted list with severity, tenant, status, and AI classification. Detail panel with full context. Actions: route to tenant, close as duplicate, request more info. GitHub integration for one-click issue creation.
**Components**:

- `app/(platform)/platform/issues/page.tsx` — issue queue orchestrator
- `app/(platform)/platform/issues/elements/IssueQueueTable.tsx` — sortable, filterable queue
- `app/(platform)/platform/issues/elements/IssueDetailPanel.tsx` — slide-out detail panel
- `app/(platform)/platform/issues/elements/IssueActions.tsx` — route, close, request info, GitHub
- `app/(platform)/platform/issues/elements/IssueSeverityBadge.tsx` — P0-P4 color-coded badge
- `app/(platform)/platform/issues/elements/GitHubIssueButton.tsx` — one-click GitHub issue creation
- `app/(platform)/platform/issues/elements/BatchActions.tsx` — bulk close/route by filter
- `app/(platform)/platform/issues/elements/IssueHeatmap.tsx` — volume by tenant/severity/category
  **Acceptance criteria**:
- [ ] Queue table: severity badge (P0-P4), tenant name, title, status, AI classification, created date
- [ ] Severity badges: P0 (red), P1 (orange), P2 (yellow), P3 (blue), P4 (gray)
- [ ] Filter by severity, tenant, status, category
- [ ] Sort by severity, created date
- [ ] Detail panel: reporter context, session data, screenshot, browser info, AI assessment
- [ ] Actions: "Route to Tenant" (notification), "Close as Duplicate" (link to original), "Request More Info"
- [ ] Status tracking: New -> In Review -> Escalated -> Resolved -> Closed
- [ ] GitHub button: one-click creates GitHub issue pre-populated with all context
- [ ] Batch actions: select multiple, bulk close/route
- [ ] Heatmap: volume by tenant x severity (Recharts heatmap)
      **Notes**: Plan 05 Sprint C1. Depends on Plan 04 issue reporting backend.

---

### FE-048: Cache analytics panel (Platform Admin)

**Effort**: 6h
**Depends on**: FE-040
**Route**: `/platform/analytics/cache`
**Description**: Cache performance analytics panel for platform admin. Overall hit rate gauge, cost saved this month, hit rate by pipeline stage, and per-index cache settings.
**Components**:

- `app/(platform)/platform/analytics/cache/page.tsx` — cache analytics orchestrator
- `app/(platform)/platform/analytics/cache/elements/HitRateGauge.tsx` — overall hit rate (Recharts radial)
- `app/(platform)/platform/analytics/cache/elements/CostSavedCard.tsx` — dollar savings this month
- `app/(platform)/platform/analytics/cache/elements/PipelineStageChart.tsx` — hit rate by stage (bar chart)
- `app/(platform)/platform/analytics/cache/elements/IndexCacheSettings.tsx` — per-index TTL slider
  **Acceptance criteria**:
- [ ] Hit rate gauge: current week overall cache hit rate (Recharts radial bar)
- [ ] Cost saved card: "$X saved this month in LLM calls eliminated" with DM Mono font
- [ ] Pipeline stage chart: bar chart showing hit rate for embedding, search, semantic caches
- [ ] Per-index settings: table with index name, current TTL, hit rate; TTL slider per index
- [ ] TTL options: disabled (0), 15min, 30min, 1h, 4h, 8h, 24h
- [ ] Settings changes call API to update cache configuration
- [ ] Data from `GET /api/v1/admin/analytics/cache/summary` and `/by-index`
      **Notes**: Plan 03 Phase C4.

---

## Agent Registry (HAR, Plan 07)

### FE-049: Public agent registry discovery page

**Effort**: 8h
**Depends on**: FE-003
**Route**: `/registry`
**Description**: Public-facing agent discovery page (no auth required to browse). Search by industry, transaction type, language. Agent cards with name, trust score, transaction count, SLA. Detail page with trust score breakdown and attestations.
**Components**:

- `app/registry/page.tsx` — public registry search
- `app/registry/elements/RegistrySearchBar.tsx` — search with industry/type/language filters
- `app/registry/elements/AgentDiscoveryGrid.tsx` — agent card grid
- `app/registry/elements/RegistryAgentCard.tsx` — name, trust score, txn count, SLA
- `app/registry/[id]/page.tsx` — agent detail page
- `app/registry/[id]/elements/TrustScoreBreakdown.tsx` — score components visualization
- `app/registry/[id]/elements/AttestationList.tsx` — KYB/verification attestations
- `app/registry/[id]/elements/CapabilityQuery.tsx` — example capability query interface
  **Acceptance criteria**:
- [ ] No authentication required to browse (public page)
- [ ] Search bar with industry, transaction type, and language filter dropdowns
- [ ] Agent cards: name, description, trust score (0-100), transaction count, SLA summary
- [ ] Trust score shown as colored badge: green (>70), yellow (40-70), red (<40)
- [ ] Trust score number in DM Mono font
- [ ] Detail page: trust score breakdown (KYB, txn volume, dispute rate, uptime, response time)
- [ ] Attestation list: KYB level, verification date, provider
- [ ] Capability query: text input to test agent capability response
- [ ] Loading skeleton for card grid
- [ ] Empty state: "No agents match your search. Try broader filters."
      **Notes**: Plan 07 Phase 0 Sprint 0-B. Basic search sorted by registration date (no AI ranking yet).

---

### FE-050: Tenant registry management

**Effort**: 6h
**Depends on**: FE-035
**Route**: `/admin/registry`
**Description**: Tenant admin interface for publishing agents to the global registry. "Publish to Global Registry" button, published agent badges, agent card configuration form, and registry analytics widget.
**Components**:

- `app/(admin)/admin/registry/page.tsx` — registry management orchestrator
- `app/(admin)/admin/registry/elements/PublishAgentFlow.tsx` — select agent + configure card + publish
- `app/(admin)/admin/registry/elements/PublishedAgentsList.tsx` — published agents with [Public] badge
- `app/(admin)/admin/registry/elements/AgentCardConfigForm.tsx` — transaction types, industries, languages, SLA
- `app/(admin)/admin/registry/elements/RegistryAnalyticsWidget.tsx` — discovery count this week
  **Acceptance criteria**:
- [ ] "Publish to Global Registry" button opens agent selection
- [ ] Agent selection: dropdown of workspace agents eligible for publishing
- [ ] Card configuration: transaction types (multi-select), industries, languages, SLA description
- [ ] Published agents shown with `[Public]` badge in list
- [ ] Published agent: edit card, unpublish actions
- [ ] Analytics widget: "Your agent was discovered X times this week"
- [ ] Calls `POST /api/v1/registry/agents` to publish
- [ ] Calls `PUT /api/v1/registry/agents/{id}` to update
- [ ] Calls `DELETE /api/v1/registry/agents/{id}` to unpublish
      **Notes**: Plan 07 Phase 0 Sprint 0-B.

---

## Profile & Memory Hooks (Plan 08)

### FE-051: React hooks for profile and memory

**Effort**: 6h
**Depends on**: FE-002
**Route**: N/A (lib-level hooks)
**Description**: Create all React hooks needed for the profile and memory system. These are shared hooks used across chat and settings pages.
**Components**:

- `lib/hooks/useUserMemory.ts` — CRUD for memory notes (list, delete single, clear all)
- `lib/hooks/useUserProfile.ts` — fetch/update profile preferences
- `lib/hooks/usePrivacySettings.ts` — profile learning toggle, org context toggles, data export/clear
  **Acceptance criteria**:
- [ ] `useUserMemory`: returns `{ notes, isLoading, deleteNote(id), clearAll() }`
- [ ] `useUserMemory` fetches from `GET /api/v1/me/memory`
- [ ] `useUserProfile`: returns `{ profile, isLoading, updateProfile(data) }`
- [ ] `useUserProfile` fetches from `GET /api/v1/me/profile`
- [ ] `usePrivacySettings`: returns `{ settings, isLoading, updateSetting(key, value), exportData(), clearAllData() }`
- [ ] All hooks use React Query for caching and revalidation
- [ ] All hooks handle loading, error, and empty states
- [ ] TypeScript: strict types for all return values (no `any`)
      **Notes**: Plan 08 Sprint 7. Used by FE-016 through FE-020 and FE-009.

---

## Tenant Admin — Memory Policy Settings (Plan 08)

### FE-052: Tenant admin memory policy settings

**Effort**: 5h
**Depends on**: FE-003
**Route**: `/admin/settings/memory`
**Description**: Tenant-level memory policy management page. Tenant admin can enable/disable profile learning, working memory, and memory notes for the entire workspace. Per-setting toggles with defaults shown.
**Components**:

- `app/(admin)/admin/settings/memory/page.tsx` — memory policy page
- `app/(admin)/admin/settings/memory/elements/ProfileLearningPolicy.tsx` — workspace-wide toggle + frequency
- `app/(admin)/admin/settings/memory/elements/WorkingMemoryPolicy.tsx` — enable/disable + TTL config
- `app/(admin)/admin/settings/memory/elements/MemoryNotesPolicy.tsx` — enable/disable + auto-extraction toggle
  **Acceptance criteria**:
- [ ] Profile learning toggle: workspace-wide enable/disable (default: enabled)
- [ ] Working memory toggle: enable/disable with TTL selector (default: 7 days)
- [ ] Memory notes toggle: enable/disable with auto-extraction toggle
- [ ] Each setting shows platform default and current override
- [ ] Save button calls `PATCH /api/v1/admin/memory-policy`
- [ ] Success toast on save
- [ ] Changes apply to all users in workspace
      **Notes**: Plan 08 Sprint 8.

---

## Tenant Admin — Issue Reporting Settings (Plan 04)

### FE-053: Tenant issue reporting configuration

**Effort**: 5h
**Depends on**: FE-003
**Route**: `/admin/settings/issue-reporting`
**Description**: Tenant-level configuration for issue reporting: integration setup (GitHub/GitLab/Jira/Linear), notification recipients, custom categories, widget appearance.
**Components**:

- `app/(admin)/admin/settings/issue-reporting/page.tsx` — settings page
- `app/(admin)/admin/settings/issue-reporting/elements/IntegrationSetup.tsx` — GitHub/GitLab/Jira/Linear config
- `app/(admin)/admin/settings/issue-reporting/elements/NotificationRecipients.tsx` — email list management
- `app/(admin)/admin/settings/issue-reporting/elements/CustomCategories.tsx` — add/edit/remove categories
- `app/(admin)/admin/settings/issue-reporting/elements/WidgetAppearance.tsx` — position, visibility settings
  **Acceptance criteria**:
- [ ] Integration selector: GitHub, GitLab, Jira, Linear — one active at a time
- [ ] GitHub integration: repository URL, bot token (masked), test connection
- [ ] Notification recipients: list of email addresses to receive issue alerts
- [ ] Custom categories: add/edit/remove beyond default (bug/performance/ux/feature)
- [ ] Widget appearance: position (bottom-right/bottom-left), always visible / chat page only
- [ ] Settings stored in `tenant_configs` (config_type='issue_reporting')
- [ ] Test connection button for each integration type
      **Notes**: Plan 04 Phase 4.

---

## Platform Admin — Engineering Queue (Plan 04)

### FE-054: Engineering issue queue view

**Effort**: 6h
**Depends on**: FE-047
**Route**: `/platform/issues/queue`
**Description**: Engineering queue view for platform admin. Filter tabs for incoming/triaged/in-progress/SLA-at-risk/resolved. Per-issue actions: accept, override severity, won't fix, request info, assign. Batch actions.
**Components**:

- `app/(platform)/platform/issues/queue/page.tsx` — queue view
- `app/(platform)/platform/issues/queue/elements/QueueFilterTabs.tsx` — status filter tabs
- `app/(platform)/platform/issues/queue/elements/IssueActionBar.tsx` — accept, override severity, won't fix, assign
- `app/(platform)/platform/issues/queue/elements/SeverityOverrideDialog.tsx` — change severity with reason
- `app/(platform)/platform/issues/queue/elements/RequestInfoDialog.tsx` — send question to reporter
- `app/(platform)/platform/issues/queue/elements/BatchActionBar.tsx` — bulk assign/close
  **Acceptance criteria**:
- [ ] Filter tabs: Incoming, Triaged, In Progress, SLA At-Risk (red count badge), Resolved
- [ ] Per-issue actions: Accept (assigns to self), Override Severity (with reason), Won't Fix (with reason)
- [ ] Request Info: sends question to reporter via notification
- [ ] Assign: assign to team member or sprint/milestone (GitHub API)
- [ ] Severity override: dialog with new severity + reason text
- [ ] Batch actions: select multiple via checkbox, bulk close/assign/route
- [ ] SLA at-risk tab: shows issues approaching deadline, sorted by urgency
      **Notes**: Plan 04 Phase 4.

---

## Platform Admin — Issues Analytics Dashboard (Plan 04)

### FE-055: Platform issues analytics dashboard

**Effort**: 6h
**Depends on**: FE-047
**Route**: `/platform/issues/analytics`
**Description**: Platform admin analytics for issue reporting: heatmap by tenant/severity, cross-tenant duplicate view, SLA adherence metrics, MTTR by severity, top bugs by volume, week-over-week trends.
**Components**:

- `app/(platform)/platform/issues/analytics/page.tsx` — analytics orchestrator
- `app/(platform)/platform/issues/analytics/elements/IssueHeatmap.tsx` — tenant x severity heatmap (Recharts)
- `app/(platform)/platform/issues/analytics/elements/DuplicateView.tsx` — cross-tenant duplicate clusters
- `app/(platform)/platform/issues/analytics/elements/SLAAdherence.tsx` — adherence rate gauge
- `app/(platform)/platform/issues/analytics/elements/MTTRChart.tsx` — MTTR by severity (bar chart)
- `app/(platform)/platform/issues/analytics/elements/TopBugsTable.tsx` — top 10 by report volume
- `app/(platform)/platform/issues/analytics/elements/TrendChart.tsx` — week-over-week line chart
  **Acceptance criteria**:
- [ ] Heatmap: tenant rows x severity columns, color intensity = volume
- [ ] Cross-tenant duplicate view: clusters of similar issues across tenants
- [ ] SLA adherence: gauge showing % of issues resolved within SLA target
- [ ] MTTR chart: bar chart showing mean time to resolution per severity (P0-P4)
- [ ] Top bugs table: rank, title, report count, tenant count, status
- [ ] Trend chart: week-over-week line chart of total issues, split by severity
- [ ] All numeric values in DM Mono font
- [ ] CSV export button for monthly report
- [ ] Note: SLA metrics are internal tracking only (Phase 1-3, no user-facing SLA promises)
      **Notes**: Plan 04 Phase 4. SLA promises deferred to Phase 4+ per canonical spec.

---

## Platform Admin — Audit and Polish (Plan 05)

### FE-056: Platform audit log UI

**Effort**: 5h
**Depends on**: FE-040
**Route**: `/platform/audit-log`
**Description**: Searchable audit event history showing all platform admin actions. Filterable by actor, resource type, action type, and date range.
**Components**:

- `app/(platform)/platform/audit-log/page.tsx` — audit log page
- `app/(platform)/platform/audit-log/elements/AuditLogTable.tsx` — paginated log table
- `app/(platform)/platform/audit-log/elements/AuditLogFilters.tsx` — actor, resource, action, date range
  **Acceptance criteria**:
- [ ] Table columns: timestamp, actor (admin name), resource (tenant/profile/tool), action, details
- [ ] Server-side pagination
- [ ] Filter by actor, resource type, action type, date range
- [ ] Search by keyword in details field
- [ ] Timestamp in DM Mono font
- [ ] Export as CSV
      **Notes**: Plan 05 Sprint D2.

---

### FE-057: Platform alert center

**Effort**: 5h
**Depends on**: FE-040
**Route**: `/platform/alerts`
**Description**: Unified alert inbox for platform admin. Aggregates quota warnings, health degradations, cost spikes, tool failures, and P0 issues. Configurable alert thresholds.
**Components**:

- `app/(platform)/platform/alerts/page.tsx` — alert center
- `app/(platform)/platform/alerts/elements/AlertList.tsx` — unified alert list
- `app/(platform)/platform/alerts/elements/AlertItem.tsx` — individual alert with type badge
- `app/(platform)/platform/alerts/elements/AlertThresholdConfig.tsx` — configurable thresholds
  **Acceptance criteria**:
- [ ] Alert list: sorted by severity then time
- [ ] Type badges: Quota (blue), Health (yellow), Cost (red), Tool (orange), Issue (red)
- [ ] Each alert: type badge, message, tenant name, timestamp, dismiss/acknowledge button
- [ ] Acknowledged alerts moved to separate tab
- [ ] Threshold config: per-alert-type thresholds (e.g., margin below X%, health below Y)
- [ ] Badge count in sidebar nav showing unacknowledged alerts
      **Notes**: Plan 05 Sprint D2.

---

## Playwright E2E Tests

### FE-058: E2E test suite — chat flows

**Effort**: 8h
**Depends on**: FE-005, FE-006, FE-007, FE-008
**Route**: `/chat`
**Description**: Playwright E2E tests for core chat functionality. Tests must use real backend (no mocking per testing rules). Covers empty state, message send/receive, SSE streaming, feedback, source panel, and confidence display.
**Components**:

- `src/web/tests/chat.spec.ts` — chat flow tests
  **Acceptance criteria**:
- [ ] Test: empty state renders with centered input and agent selector
- [ ] Test: sending message transitions to active state
- [ ] Test: SSE streaming renders progressive text
- [ ] Test: thumbs up/down submits feedback
- [ ] Test: source panel opens and shows source cards
- [ ] Test: retrieval confidence badge shows correct label
- [ ] Test: conversation list loads and navigation works
- [ ] All tests use real backend (no mocking)
- [ ] Tests run against `NEXT_PUBLIC_API_URL` from env
      **Notes**: Per testing rules, Tier 3 tests use real everything.

---

### FE-059: E2E test suite — tenant admin flows

**Effort**: 8h
**Depends on**: FE-027, FE-029, FE-033
**Route**: `/admin/*`
**Description**: Playwright E2E tests for tenant admin console. Tests user invite, document store connection, glossary management, and workspace settings.
**Components**:

- `src/web/tests/tenant-admin.spec.ts` — tenant admin flow tests
  **Acceptance criteria**:
- [ ] Test: invite user via single email + verify appears in directory
- [ ] Test: change user role via dropdown
- [ ] Test: SharePoint wizard completes connection test
- [ ] Test: add glossary term with character limit enforcement
- [ ] Test: bulk CSV glossary import with preview
- [ ] Test: workspace name change persists
- [ ] Test: cross-tenant isolation (tenant A admin cannot see tenant B users)
- [ ] All tests use real backend (no mocking)
      **Notes**: Per testing rules, Tier 3 tests use real everything. Per god-mode rules, create missing records if 404.

---

### FE-060: E2E test suite — platform admin flows

**Effort**: 8h
**Depends on**: FE-041, FE-043
**Route**: `/platform/*`
**Description**: Playwright E2E tests for platform admin console. Tests tenant provisioning, LLM profile management, and issue queue.
**Components**:

- `src/web/tests/platform-admin.spec.ts` — platform admin flow tests
  **Acceptance criteria**:
- [ ] Test: platform admin can provision new tenant (full wizard)
- [ ] Test: provisioning SSE shows step-by-step progress
- [ ] Test: suspend tenant and verify status change
- [ ] Test: create LLM profile and publish
- [ ] Test: assign LLM profile to tenant
- [ ] Test: platform RBAC enforced (platform_support cannot modify quotas)
- [ ] All tests use real backend (no mocking)
      **Notes**: Per testing rules, Tier 3 tests use real everything.

---

### FE-061: E2E test suite — privacy and memory flows

**Effort**: 6h
**Depends on**: FE-016, FE-019, FE-020
**Route**: `/settings/privacy`
**Description**: Playwright E2E tests for privacy settings and memory management. Tests profile toggle, memory notes CRUD, data export, and clear all.
**Components**:

- `src/web/tests/privacy-memory.spec.ts` — privacy and memory flow tests
  **Acceptance criteria**:
- [ ] Test: profile learning toggle persists on page reload
- [ ] Test: "How does this work?" opens PrivacyDisclosureDialog (not a consent gate)
- [ ] Test: memory note appears after "remember that" in chat
- [ ] Test: delete individual memory note
- [ ] Test: clear all memory notes with confirmation
- [ ] Test: export data downloads JSON file
- [ ] Test: clear all learning data wipes profile + notes + working memory
- [ ] All tests use real backend (no mocking)
      **Notes**: Plan 08 Sprint 7. 10 critical flow tests per Definition of Done.

---

## Summary

| Category                                | Todos            | Estimated Hours |
| --------------------------------------- | ---------------- | --------------- |
| Project Setup                           | FE-001 to FE-003 | 20h             |
| Core Chat (End User)                    | FE-004 to FE-015 | 54h             |
| Privacy Settings (End User)             | FE-016 to FE-020 | 21h             |
| Issue Reporting                         | FE-021 to FE-025 | 28h             |
| Tenant Admin Console                    | FE-026 to FE-038 | 102h            |
| Teams Management                        | FE-039           | 10h             |
| Platform Admin Portal                   | FE-040 to FE-048 | 62h             |
| Agent Registry (HAR)                    | FE-049 to FE-050 | 14h             |
| Profile & Memory Hooks                  | FE-051 to FE-052 | 11h             |
| Tenant Settings (Issues)                | FE-053           | 5h              |
| Platform Issues (Eng Queue + Analytics) | FE-054 to FE-055 | 12h             |
| Platform Audit & Alerts                 | FE-056 to FE-057 | 10h             |
| Playwright E2E Tests                    | FE-058 to FE-061 | 30h             |
| Gap Remediation                         | FE-062 to FE-063 | 9h              |
| **Total**                               | **63 todos**     | **~388h**       |

---

## Dependency Graph (Critical Path)

```
---

## Gap Remediation (from 07-gap-analysis.md)

### FE-062: Install DOMPurify and SafeHTML component

**Effort**: 4h
**Depends on**: FE-001
**Route**: N/A (lib-level)
**Description**: Install DOMPurify and create a `SafeHTML` component for rendering user-generated content safely. All user content (memory notes, chat messages, glossary definitions, agent descriptions, issue report descriptions) must be rendered via `textContent` or sanitized before any `innerHTML`. React prevents most XSS but not all — `dangerouslySetInnerHTML` and markdown rendering are attack vectors.
**Components**:

- `lib/safe-html.tsx` — `SafeHTML` component wrapping DOMPurify
- `lib/sanitize.ts` — `sanitize(html)` utility function
  **Acceptance criteria**:
- [ ] DOMPurify installed and configured
- [ ] `SafeHTML` component: accepts raw HTML, outputs sanitized HTML
- [ ] `SafeHTML` strips `<script>`, `onclick`, `onerror`, `javascript:` URIs
- [ ] `SafeHTML` allows safe tags: `<p>`, `<br>`, `<strong>`, `<em>`, `<a>` (with rel=noopener)
- [ ] `sanitize(text)` utility for non-HTML contexts (escapes all HTML entities)
- [ ] ESLint rule: warn on `dangerouslySetInnerHTML` without SafeHTML wrapper
- [ ] All user-generated content rendering points audited and updated
      **Notes**: GAP-003. HIGH. User-generated content rendered without sanitization is an XSS vector.

### FE-063: Global and route-level Error Boundaries

**Effort**: 5h
**Depends on**: FE-001
**Route**: N/A (app-level)
**Description**: React Error Boundaries to prevent full-page crashes from component errors. Global boundary at app level catches unhandled errors. Route-level boundaries around high-risk components: SSE consumer (malformed events), Recharts (invalid data), TanStack Table (rendering errors). Each boundary shows a recovery UI with retry button.
**Components**:

- `app/error.tsx` — global error boundary (Next.js convention)
- `app/(chat)/chat/error.tsx` — chat-specific error boundary
- `app/(admin)/admin/error.tsx` — admin console error boundary
- `app/(platform)/platform/error.tsx` — platform admin error boundary
- `components/ui/error-boundary.tsx` — reusable component-level boundary
  **Acceptance criteria**:
- [ ] `app/error.tsx`: catches unhandled errors, shows recovery UI with "Try Again" button
- [ ] Chat error boundary: catches SSE parsing errors, shows "Connection lost, reconnecting..."
- [ ] Admin error boundary: catches table/chart rendering errors, shows fallback with data dump
- [ ] Component-level `ErrorBoundary`: wraps Recharts and TanStack Table instances
- [ ] All error boundaries log errors to console and optional error reporting service
- [ ] Recovery UI matches Obsidian Intelligence design system
- [ ] Error boundaries do NOT catch errors in event handlers (React limitation — documented)
      **Notes**: GAP-022. HIGH. 61 component todos with zero Error Boundaries. A single malformed SSE event could crash the entire chat UI.

---

## Dependency Graph (Critical Path)

```

FE-001 (setup)
└─> FE-002 (API/auth)
└─> FE-003 (shell/nav)
├─> FE-004 (chat empty) ─> FE-005 (chat active/SSE)
│ ├─> FE-006 (feedback)
│ ├─> FE-007 (source panel)
│ ├─> FE-008 (confidence badge)
│ ├─> FE-009 (profile indicator)
│ ├─> FE-010 (team badge)
│ ├─> FE-011 (team selector)
│ ├─> FE-012 (memory toast)
│ ├─> FE-013 (glossary indicator)
│ ├─> FE-014 (cache chip)
│ └─> FE-015 (conversation list)
├─> FE-016 (privacy page) ─> FE-017, FE-018, FE-019, FE-020
├─> FE-021 (issue button) ─> FE-022 (issue dialog) ─> FE-023 (error detect)
├─> FE-024 (my reports)
├─> FE-025 (notification bell)
├─> FE-026 (admin dashboard) ─> FE-038 (onboarding wizard)
├─> FE-027 (user directory)
├─> FE-028 (workspace settings)
├─> FE-029 (doc stores) ─> FE-030 (gdrive), FE-031 (sync failures), FE-034 (sync health)
├─> FE-032 (SSO wizard)
├─> FE-033 (glossary)
├─> FE-035 (agent library) ─> FE-036 (agent studio), FE-050 (registry mgmt)
├─> FE-037 (analytics)
├─> FE-039 (teams)
├─> FE-040 (platform dashboard) ─> FE-041 to FE-048
└─> FE-049 (public registry)

```

```
