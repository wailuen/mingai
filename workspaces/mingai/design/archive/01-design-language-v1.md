# mingai Design Language — Obsidian Intelligence

**Date**: 2026-03-06
**Prototype reference**: `workspaces/mingai/99-ui-proto/index.html`
**Status**: Active — established through iterative prototype review

---

## 1. Design System Name

**Obsidian Intelligence** — dark-first enterprise AI design system. Named for the dark volcanic glass quality of the base palette: deep, polished, and purposeful. The accent color provides a single sharp focal point, like light refracting through obsidian.

---

## 2. Color Tokens

### Dark Mode (default)

```css
--bg-base:      #0C0E14;   /* page background */
--bg-surface:   #161A24;   /* cards, sidebars, topbar */
--bg-elevated:  #1E2330;   /* inputs, badges, hover states */
--bg-deep:      #0A0C12;   /* deepest inset areas */

--border:       #2A3042;   /* primary dividers */
--border-faint: #1E2330;   /* subtle row separators */

--accent:       #4FFFB0;   /* primary mint green */
--accent-dim:   rgba(79,255,176,.08);   /* accent fill background */
--accent-ring:  rgba(79,255,176,.28);   /* accent border/glow */

--alert:        #FF6B35;   /* error / P1 severity */
--alert-dim:    rgba(255,107,53,.08);
--alert-ring:   rgba(255,107,53,.28);

--warn:         #F5C518;   /* warning / P2 / at-risk */
--warn-dim:     rgba(245,197,24,.08);

--text-primary: #F1F5FB;
--text-muted:   #8892A4;
--text-faint:   #4A5568;
```

### Light Mode

```css
--bg-base:      #F2F4F9;
--bg-surface:   #FFFFFF;
--bg-elevated:  #EDF0F7;
--border:       #D8DCE8;
--border-faint: #EDF0F7;
--accent:       #00A86B;   /* darkened mint — accessible on white */
--accent-dim:   rgba(0,168,107,.08);
--accent-ring:  rgba(0,168,107,.25);
--text-primary: #0F1118;
--text-muted:   #4A5568;
--text-faint:   #9AA3B2;
```

### Color usage rules

- **Accent** is used only for: active states, CTA buttons, confirmation indicators, trust scores, positive metrics. Never for decorative fills or backgrounds.
- **Alert (orange)** for: P0/P1 issues, at-risk tenant signals, sync failures, satisfaction drops.
- **Warn (yellow)** for: P2 issues, quota warnings, health scores 50-70, satisfaction 70-80%.
- **Accent green on text** only when the metric is unambiguously positive. Never use it for neutral data.

---

## 3. Typography

### Final Stack (adopted 2026-03-06)

| Role | Font | Weights |
|------|------|---------|
| Display / Headings / Nav labels | **Plus Jakarta Sans** | 400, 500, 600, 700, 800 |
| Body / UI text | **Plus Jakarta Sans** | 400, 500 |
| Data / Numbers / Badges / Code | **DM Mono** | 400, 500 |

```css
font-family: 'Plus Jakarta Sans', sans-serif;   /* all UI text */
font-family: 'DM Mono', monospace;               /* data & metrics */
```

Google Fonts import:
```
https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap
```

### Rejected options (and why)

| Stack | Character | Rejected because |
|-------|-----------|------------------|
| Syne + JetBrains Mono + Inter | Quirky editorial | Syne too narrow for dense data tables; felt mismatched with enterprise context |
| Space Grotesk + Space Mono | Geometric, sci-fi edge | Too distinctive — difficult to scale to all contexts, Space Mono too wide in tables |
| DM Sans + DM Mono | Minimal, neutral | Too flat — loses visual hierarchy in dense admin screens |
| Outfit + IBM Plex Mono | Structured, enterprise | IBM Plex Mono too tall; letterspacing increases table row heights undesirably |

### Typography scale

```css
/* Page titles */
font-family: 'Plus Jakarta Sans'; font-size: 22px; font-weight: 700;

/* Section headings */
font-family: 'Plus Jakarta Sans'; font-size: 15px; font-weight: 600;

/* Body / table rows */
font-family: 'Plus Jakarta Sans'; font-size: 13px; font-weight: 400-500;

/* Labels / metadata / nav section headers */
font-family: 'Plus Jakarta Sans'; font-size: 11px; font-weight: 500-600;
letter-spacing: .06-.08em; text-transform: uppercase;

/* Data values (metrics, IDs, timestamps, monospaced) */
font-family: 'DM Mono'; font-size: 12-14px; font-weight: 400-500;
```

---

## 4. Spacing & Radius

```css
--r:    7px;    /* standard controls — inputs, buttons, chips */
--r-lg: 10px;   /* cards, panels, modals */
--r-sm: 4px;    /* badges, small chips, table cell accents */

/* Sidebar width */
--sidebar-w: 216px;   /* default; user-resizable 180px – 25vw */

/* Topbar height */
--topbar-h: 48px;
```

### Spacing guidelines
- Card padding: `20px`
- Admin content area padding: `28px 32px`
- Sidebar item padding: `8px 16px`
- Table cell padding: `12px 14px`
- Gap between KPI cards: `12px`
- Gap between major sections: `24-28px`

---

## 5. Component Decisions

### 5.1 Filter Chips

**Rule**: Filter chips are **outlined/neutral by default**, not filled with accent color.

```css
/* Correct */
.filter-chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.filter-chip:hover {
  border-color: var(--accent-ring);
  color: var(--text-primary);
  background: var(--accent-dim);
}

/* Wrong — do not do this */
/* background: var(--accent-dim); border: 1px solid var(--accent-ring); color: var(--accent); */
```

Rationale: Filled accent chips read as "selected" or "active". Neutral chips are the correct idle state.

### 5.2 Sidebar: Resizable Width

**Rule**: The end-user sidebar is user-resizable via a drag handle at the right edge.

- **Default width**: `216px`
- **Minimum width**: `180px` (below this text becomes unusable)
- **Maximum width**: `25vw` (keeps content area dominant)
- Handle: `5px` wide invisible zone at the right edge of the sidebar; `cursor: col-resize`; highlights on hover (`var(--border)`) and during drag (`var(--accent-ring)`)
- During drag: disable `transition` on the sidebar (`is-resizing` class removes it) to prevent jank
- Width is NOT persisted across sessions in the prototype; production should use `localStorage`

```css
/* Resize handle */
.sidebar-resize-handle {
  position: absolute;
  top: 0; right: -2px; width: 5px; height: 100%;
  cursor: col-resize;
  background: transparent;
}
.sidebar-resize-handle:hover { background: var(--border); }
.sidebar.is-resizing .sidebar-resize-handle { background: var(--accent-ring); }
.sidebar.is-resizing { transition: none; }
```

### 5.3 History Items: Hover Actions

**Rule**: Rename (✎) and Delete (✕) actions appear on history items on pointer hover, absolutely positioned at the right edge with a gradient fade.

- **Idle state**: only the truncated title is visible; full title exposed via native `title` attribute (browser tooltip on hover)
- **Hover state**: `opacity: 0 → 1` on `.s-hist-actions`; gradient mask (`linear-gradient(to right, transparent, var(--bg-elevated))`) prevents text bleed-through
- **`title` attribute**: always set to the full conversation title on the wrapper element; updated in sync when the user renames the item
- **Rename**: replaces the title `<span>` with an `<input>` inline; confirms on `Enter` or `blur`; cancels on `Escape`
- **Delete**: fades + slides the item out (`opacity: 0`, `translateX(-6px)`, 180ms) then removes from DOM
- Action buttons: `20×20px`, `border-radius: 3px`; rename neutral hover, delete uses `var(--alert)` on hover

```css
.s-hist-actions {
  position: absolute; right: 0; top: 0; bottom: 0;
  opacity: 0; pointer-events: none;
  transition: opacity 120ms;
}
.s-hist-item:hover .s-hist-actions { opacity: 1; pointer-events: all; }
.s-hist-btn.s-hist-del:hover { color: var(--alert); }
```

### 5.4 Chat: Two-State Layout

The chat screen has two distinct states. This pattern mirrors the aihub2 implementation.

**Empty state** — full-height centered layout:
- Agent identity mark (icon, 44×44px, accent-dim fill)
- Personalised greeting ("Good morning, Sarah.")
- Agent subtitle ("What does Finance need today?")
- Input bar embedded in the centered layout — NOT at the bottom
- KB hint below input: e.g. "SharePoint · Google Drive · 2,081 documents indexed"
- Suggestion chips below KB hint

**Active state** — triggered on first message:
- Empty state hidden (`display: none`)
- Messages scroll area fills the space (`max-width: 860px`, centred)
- Input bar fixed at the bottom

```javascript
// State transitions
function activateChatState()  // empty → active on first send
function resetChatState()     // active → empty on agent switch
function dispatchQuery(text)  // shared logic for both states
```

### 5.5 Chat: Message Rendering Pattern

**Rule**: AI responses render directly on the page background — no card, no border, no background fill. User messages use a contained pill. This matches the modern LLM chat pattern (Grok, Claude.ai, aihub2).

| Turn | Treatment |
|------|-----------|
| User | Right-aligned pill — `background: var(--bg-elevated)`, `border: 1px solid var(--border)`, `border-radius: var(--r-lg)`, `max-width: 68%` |
| AI | Full-width, no box. Text flows directly on `--bg-base`. Meta row above, footer (sources + latency + feedback) below. |

**AI response anatomy** (top to bottom):
1. **Meta row** — `AGENT NAME · MODE` label (accent, uppercase, 11px) + confidence pill + personalised badge
2. **Response text** — `font-size: 14px`, `line-height: 1.6`, `color: var(--text-primary)` — plain text, no container
3. **Footer row** — `⊞ N sources` button + latency in DM Mono (`text-faint`) — no separator line
4. **Feedback row** — 👍 👎 buttons; on 👎: tag chips + optional textarea inline below

**What NOT to do**:
- Never wrap the AI response in a card with `background` + `border` — this is the old "chat bubble" pattern
- Never show latency as a floating indicator above the input bar — it lives in the response footer only

```css
/* User message */
.msg-user-bubble {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 10px 14px;
}

/* AI message: no box */
.msg-ai-inner { padding: 0; }
```

### 5.6 KB Hint Display

**Rule**: Knowledge Base information shown to end users must be human-readable, not technical.

```
// Correct
"SharePoint · Google Drive · 2,081 documents indexed"

// Wrong — never show internal architecture labels to end users
"RAG · SharePoint + Google Drive · 2,081 docs"
```

KB hint lives below the input in the empty state. It is a single subtle line (`font-size: 11px`, `color: var(--text-faint)`), with a small accent-colored dot indicator before the text.

### 5.7 Topbar: Single-Level Navigation

**Rule**: No secondary topbar inside individual screens. The global topbar breadcrumb handles all context.

```
// Topbar breadcrumb pattern
[Screen/Agent Name] › [Sub-context]
e.g. "Finance Agent › General"
e.g. "Registry › Discover"
e.g. "Escalations"
```

The chat screen must not have its own topbar repeating the agent name. This was identified and fixed — the `chat-topbar` element was removed.

### 5.9 Chat Input: Attach Button

**Rule**: A document upload (attach) button sits between the mode selector / Research button and the text input in the chat input bar.

- Icon: paperclip SVG, `14×14px`
- Size: `30×30px` button, `border-radius: var(--r-sm)`
- Idle: `color: var(--text-faint)`, no background
- Hover: `color: var(--text-muted)`, `background: var(--bg-overlay)`
- No text label — icon only; `title="Attach document"` for accessibility
- In prototype: shows a dismissible toast on click. In production: opens file picker.

```
Input bar order: [Mode selector] [Research] [Attach] [Text input ————] [Send ↑]
```

### 5.10 History: Date Grouping + Active State

**Date section labels** group history items into time buckets:

```
TODAY
  [item]
  [item]
  [item]
LAST 7 DAYS
  [item]
  [item]
EARLIER
  [item]
  [item]
```

Labels: `font-size: 10px`, `font-weight: 600`, `letter-spacing: .06em`, `text-transform: uppercase`, `color: var(--text-faint)`, `padding: 8px 10px 2px`, `pointer-events: none`.

**History search** input sits between the "History" section heading and the first date label:
- Full-width of sidebar content, `font-size: 11px`, `background: var(--bg-elevated)`, `border: 1px solid var(--border)`, `border-radius: var(--r-sm)`, `padding: 5px 8px`
- Focus: `border-color: var(--accent-ring)`

**Active state** (selected conversation):
```css
.s-hist-item.s-hist-active {
  color: var(--text-primary);
  background: var(--bg-elevated);
}
.s-hist-item.s-hist-active::before {
  content: ''; position: absolute; left: 0; top: 4px; bottom: 4px;
  width: 2px; background: var(--accent); border-radius: 1px;
}
```

### 5.11 Tab Navigation Pattern

Used in: Issues screen (Queue / Overview), Cost Analytics (Overview / Infrastructure / Alert Settings), Settings (Integrations / Access Control / Issue Reporting).

```css
/* Tab bar */
.admin-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }

/* Individual tab */
.admin-tab { padding: 8px 14px; font-size: 12px; font-weight: 500; color: var(--text-faint);
  border-bottom: 2px solid transparent; cursor: pointer; transition: var(--t); }
.admin-tab:hover { color: var(--text-muted); }

/* Active tab */
.admin-tab.active { color: var(--text-primary); border-bottom-color: var(--accent); }
```

JS pattern (prototype): simple `style.display` toggle via `onclick`. Each tab shows/hides a corresponding content div.

### 5.12 Slide-In Detail Panel

Used in: Tenant detail (from Tenants table "Manage"), Source citations panel (end-user chat).

- Slides in from the right side of the content area (or replaces content area)
- Header: entity name + status badge + close (×) button
- Sections: Identity info → Metrics → Quick Actions
- **Destructive actions** (Suspend, Delete) styled in `--alert`, placed last in the actions group and visually separated

```
Panel structure:
  ┌─ Header: Name · Status badge · × ──────────────────────┐
  │  Section: Identity (plan, subdomain, contact, LLM)     │
  │  Section: Health score + trend + signals               │
  │  Section: Usage metrics                                │
  │  Section: Actions [Upgrade] [Change Profile] [Suspend] │
  └────────────────────────────────────────────────────────┘
```

### 5.13 Wizard / Step Modal Pattern

Used in: New Tenant provisioning, Onboarding wizard (tenant setup).

- Centered overlay modal, `max-width: 640px`, `border-radius: var(--r-lg)`
- Progress bar across the top: filled to current step proportion, accent color
- Step number shown: "Step 2 of 4"
- Navigation: [← Back] (ghost) + [Next →] or [Provision / Submit] (primary) in footer
- Close (×) in top-right corner; clicking overlay dismisses

```
Modal structure:
  ┌─ Progress bar ══════════░░░░ ─────────────────── × ──┐
  │  Step N of M                                         │
  │  [Step content]                                      │
  │                                                      │
  │            [← Back]  [Next →]                       │
  └──────────────────────────────────────────────────────┘
```

Recommended plan cards (radio select): side-by-side cards with name, price, token limit; recommended option highlighted with accent border.

### 5.8 Theme Toggle

**Rule**: Single icon button in the topbar right. Click cycles through three modes in order: **Dark → Light → System → Dark**.

| Mode | Icon | Behaviour |
|------|------|-----------|
| Dark | ☽ | Forces `data-theme="dark"` |
| Light | ☀ | Forces `data-theme="light"` |
| System | ◐ | Mirrors OS `prefers-color-scheme`; updates live if OS setting changes |

- Default on load: **System** (mirrors OS preference)
- Cycle order: System → Light → Dark → System
- No dropdown — single click advances the cycle
- Button `title` attribute shows the current mode (e.g. `"Theme: Dark — click to cycle"`)

---

## 6. Information Architecture & Terminology

### 6.1 End-User Navigation

The end-user sidebar contains one element: conversation History.

```
HISTORY
  [recent conversations]
```

**Rationale**:
- **No agent list**: end users do not navigate between agents. The orchestrator routes queries automatically. Exposing a list of Finance / HR / Legal items in the sidebar implies the user must choose — which contradicts the unified chat model described in `03-user-flows/03-end-user-flows.md`.
- **Manual routing = mode selector in the input bar**: when a user wants to lock to a specific agent (e.g. Finance, HR, Legal), they use the Auto / agent dropdown in the input bar. The sidebar is never involved in routing.
- **Registry is RBAC-gated**: the Registry (Discover / My Agents / Transactions) is visible only to roles with agent procurement permissions (e.g. Procurement, Sales operators). Standard end users do not see it in the sidebar.
- **No Escalations**: expert escalation / HITL routing is deferred to a future phase. The concept is removed from the end-user view entirely.

### 6.2 Agent Types (visible vs transparent)

| Type | Visibility | Examples |
|------|------------|---------|
| Deployed agents | Selectable via mode selector in input bar | Finance, HR, Legal, Procurement |
| A2A integration agents | Transparent to end users | Bloomberg, CapIQ, SharePoint Sync |

End users access deployed agents through the Auto / agent mode selector in the input bar, not via a sidebar list. A2A/integration agents are backend infrastructure.

### 6.3 Role Switcher

The topbar contains a role switcher pill allowing prototype navigation between the three views. In production, this would be separate authenticated sessions.

```
End User       →  Chat + Registry
Tenant Admin   →  Workspace admin console (Acme Corp Knowledge AI)
Platform Admin →  Cross-tenant admin console (mingai platform)
```

---

## 7. Three-Role UI Architecture

### 7.1 End User View

- Full dark-mode chat interface
- Left sidebar: History only
- Right panel: Source citations (slides in)
- Screens: Chat (+ Registry for permitted roles)

### 7.2 Tenant Admin View (`admin-app` overlay)

Admin console for one tenant's workspace. Covers full viewport.

**Left nav sections**: Workspace, Insights
**Nav items**: Dashboard, Documents, Users, Agents, Glossary | Analytics, Issues, Settings

**Screen inventory**:
- **Dashboard**: Setup checklist + weekly KPI cards + alert panel
- **Documents**: Sync status cards (SharePoint/Google Drive) + Knowledge Bases table + Full Re-Index action
- **Users**: User table (role, agents, last active) + Pending Requests badge + Invite Users
- **Agents**: Deployed agent cards + Browse Library + Agent Studio (new custom agent builder)
- **Glossary**: Term list + Suggested Additions banner + Add Term / Import CSV
- **Analytics**: KPI cards + Agent Performance table + **Content Gaps table** + **Feedback Tag breakdown**
- **Issues**: Queue/Overview tabs + issue rows with reference (rpt_XXXXX), SLA target, AI triage; resolution metrics in Overview tab
- **Settings**: 3 tabs — Integrations (connected sources) / Access Control (access requests) / Issue Reporting (GitHub, SLA overrides, notifications)

**Key data displayed (Acme Corp)**:
- Setup checklist: 3/5 complete (workspace, SSO, SharePoint connected; agents and glossary pending)
- Sync: SharePoint healthy (1,247 docs), Google Drive warning (12 failed, 2.5h stale)
- Agents: Finance Analyst 74%, HR Helper 89%, Procurement Assistant 63% (stale KB alert)
- Glossary: 44 terms, 3 suggested additions (EMEA 47×, Project Falcon 23×, RFP 12×)
- Content Gaps: 5 unanswered query topics (top: "Preferred vendor list" 18×)
- Feedback tags: Incomplete 41%, Inaccurate 26%, Irrelevant 21%, Hallucinated 12%

### 7.3 Platform Admin View (`admin-app` overlay)

Cross-tenant operations console. Covers full viewport.

**Left nav sections**: Operations, Intelligence, Finance
**Nav items**: Dashboard, Tenants, Issue Queue | LLM Profiles, Agent Templates, Analytics, Tool Catalog | Cost Analytics

**Screen inventory**:
- **Dashboard**: KPI cards + At-Risk Tenants panel + All Tenants table (+ New Tenant wizard modal)
- **Tenants**: Tenant table with plan/health/quota + Tenant Detail slide-in panel (suspend, quota override, LLM profile change)
- **Issue Queue**: Issue list with reference (rpt_XXXXX), SLA countdown, severity badge (overrideable), cross-tenant duplicate indicator; action buttons: Create GitHub Issue / Route to Tenant / Close Duplicate / Request Info
- **LLM Profiles**: Profile cards (published/draft/deprecated) + profile slot configuration
- **Agent Templates**: Template table with satisfaction + version history + Edit/Publish
- **Analytics**: Feature Adoption table (usage across tenants) + Roadmap Signals (top feature requests + pain points)
- **Tool Catalog**: MCP tool table with classification (Read-Only/Write/Execute) + health status
- **Cost Analytics**: 3 tabs — Overview (per-tenant cost + margin table) / Infrastructure / Alert Settings (budget thresholds)

**Key data displayed**:
- 24 active tenants / 3 at-risk / 67.2% gross margin / 1 P1 issue / 2 quota warnings
- At-risk: BetaCo (41, −12/wk), Initech (54, quota 91%), NovaCorp (58, error rate 7%)
- Cost: $4,823 LLM MTD, $18,500 revenue, 67.2% margin (projected 64.8% month-end)
- Analytics: Document Upload 22/24 tenants (top adoption), Glossary 6/24 (low adoption flag)
- Roadmap: Slack integration top request (14 req, 8 tenants)

---

## 8. Severity & Status Colour Mapping

| Severity / Status | Colour | Usage |
|-------------------|--------|-------|
| P0 | `#FF3547` (red) | Critical — on-call alert |
| P1 | `--alert` orange | Engineering escalation |
| P2 | `--warn` yellow | Standard triage |
| P3/P4 | `--bg-elevated` grey | Routine queue |
| Active / Healthy | `--accent` green | Normal operation |
| At Risk / Warning | `--warn` yellow | Attention needed |
| Suspended / Error | `--alert` orange | Action required |
| Pending / Inactive | grey / `--text-faint` | No urgency |

Health score colour thresholds:
- 70+ → accent green
- 50-69 → warn yellow
- < 50 → alert orange/red

---

## 9. Admin Table Pattern

Standard data table used across Platform Admin and Tenant Admin:

```css
.admin-table th  — 11px, uppercase, letter-spacing .05em, --text-faint
.admin-table td  — 13px, vertical-align middle, 12px 14px padding
/* Row hover: background: var(--accent-dim) */
/* No border on last row */
```

Data values in tables always use **DM Mono** for numbers, IDs, dates, and percentages.
Labels/names use **Plus Jakarta Sans** at `font-weight: 500`.

---

## 10. Transition & Animation

```css
--t: background 220ms ease, color 220ms ease, border-color 220ms ease, box-shadow 220ms ease;
```

- Screen transitions: `fadeIn 260ms ease`
- No heavy animations — enterprise product, information density is high
- Loading states: inline spinner, never full-page blocking overlays
- Chat response: thinking indicator (animated dots), then message streams in

---

## 11. Scrollbar Styling

```css
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
```

Minimal, unobtrusive. Does not compete with content.

---

## 12. Design Principles

1. **Data before decoration** — numbers and status signals are always the most prominent element on any screen. No decorative fills or gradients that aren't communicating information.

2. **Single accent** — `#4FFFB0` is used sparingly and always meaningfully. It should feel like a signal, not wallpaper.

3. **Dark by default** — the dark theme is the primary designed experience. Light mode is a supported alternative, not the baseline. System mode defers to the OS `prefers-color-scheme` setting.

4. **Density without clutter** — admin screens carry high information density. Spacing is deliberate. Every row, card, and column earns its place.

5. **Role clarity** — the three roles (End User, Tenant Admin, Platform Admin) have distinctly different needs and navigation patterns. They are never mixed in a single layout.

6. **Confidence through typography** — DM Mono for all numeric/data values communicates precision and reliability. Mixing body font into data columns erodes trust.
