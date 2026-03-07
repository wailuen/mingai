# Obsidian Intelligence — Design System Rules

## Scope

These rules apply to ALL frontend files: `**/*.tsx`, `**/*.jsx`, `**/*.html`, `**/*.css`, `**/*.scss`

## System

**Obsidian Intelligence** — dark-first enterprise AI design system. Dark theme is the primary designed experience. Light mode is a supported alternative.

**Visual reference**: For spatial/layout questions, screenshot `workspaces/99-ui-proto/index.html` via Playwright. The prototype is the ground truth for all layout relationships and state transitions.

---

## Color Tokens

### Dark Mode (default)

```css
--bg-base: #0c0e14; /* page background */
--bg-surface: #161a24; /* cards, sidebars, topbar */
--bg-elevated: #1e2330; /* inputs, badges, hover states */
--bg-deep: #0a0c12; /* deepest inset areas */
--border: #2a3042;
--border-faint: #1e2330;
--accent: #4fffb0; /* mint green — active states, CTAs, positive metrics */
--accent-dim: rgba(79, 255, 176, 0.08);
--accent-ring: rgba(79, 255, 176, 0.28);
--alert: #ff6b35; /* P0/P1 errors, sync failures */
--alert-dim: rgba(255, 107, 53, 0.08);
--alert-ring: rgba(255, 107, 53, 0.28);
--warn: #f5c518; /* P2, quota warnings, health 50-70 */
--warn-dim: rgba(245, 197, 24, 0.08);
--text-primary: #f1f5fb;
--text-muted: #8892a4;
--text-faint: #4a5568;
--t:
  background 220ms ease, color 220ms ease, border-color 220ms ease,
  box-shadow 220ms ease;
```

### Light Mode

```css
--bg-base: #f2f4f9;
--bg-surface: #ffffff;
--bg-elevated: #edf0f7;
--border: #d8dce8;
--border-faint: #edf0f7;
--accent: #00a86b; /* darkened mint — accessible on white */
--accent-dim: rgba(0, 168, 107, 0.08);
--accent-ring: rgba(0, 168, 107, 0.25);
--text-primary: #0f1118;
--text-muted: #4a5568;
--text-faint: #9aa3b2;
```

### Color usage rules

- **Accent** only for: active states, CTA buttons, confirmation, trust scores, positive metrics. Never decorative.
- **Alert (orange)**: P0/P1 issues, at-risk signals, sync failures, satisfaction drops.
- **Warn (yellow)**: P2 issues, quota warnings, health 50-69, satisfaction 70-80%.
- Never use accent green on neutral/ambiguous data.

---

## Typography

| Role                              | Font                  | Weights                 |
| --------------------------------- | --------------------- | ----------------------- |
| All UI text — headings, body, nav | **Plus Jakarta Sans** | 400, 500, 600, 700, 800 |
| Data, numbers, IDs, badges, code  | **DM Mono**           | 400, 500                |

```css
font-family: "Plus Jakarta Sans", sans-serif;
font-family: "DM Mono", monospace; /* data & metrics only */
```

### Scale

```css
/* Page title */     22px / 700 / Plus Jakarta Sans
/* Section heading */15px / 600 / Plus Jakarta Sans
/* Body / rows */    13px / 400-500 / Plus Jakarta Sans
/* Labels / nav */   11px / 500-600 / Plus Jakarta Sans — letter-spacing .06-.08em; text-transform: uppercase
/* Data values */    12-14px / 400-500 / DM Mono
```

---

## Spacing & Radius

```css
--r: 7px; /* controls — inputs, buttons, chips */
--r-lg: 10px; /* cards, panels, modals */
--r-sm: 4px; /* badges, small chips */
--sidebar-w: 216px; /* resizable 180px – 25vw */
--topbar-h: 48px;
```

- Card padding: `20px`
- Admin content area: `28px 32px`
- Sidebar item: `8px 16px`
- Table cell: `12px 14px`
- KPI card gap: `12px`
- Section gap: `24-28px`

---

## Component Rules

### Filter Chips — outlined neutral by default

```css
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
/* NEVER fill chips with accent-dim at idle — that signals "selected" */
```

### Chat: Two-State Layout

**Empty state**: centered layout — agent icon (44×44px), greeting, subtitle, input bar embedded (NOT bottom-fixed), KB hint below input, suggestion chips.

**Active state** (triggered on first message): messages scroll area (`max-width: 860px`, centered), input bar fixed at bottom.

```javascript
activateChatState(); // empty → active on first send
resetChatState(); // active → empty on agent switch
```

### Chat: Message Rendering

| Turn | Treatment                                                                                                                        |
| ---- | -------------------------------------------------------------------------------------------------------------------------------- |
| User | Right-aligned pill — `bg: var(--bg-elevated)`, `border: 1px solid var(--border)`, `border-radius: var(--r-lg)`, `max-width: 68%` |
| AI   | No box, no card, no border. Text flows on `--bg-base` directly.                                                                  |

AI response anatomy: (1) meta row: `AGENT · MODE` in accent, 11px uppercase + confidence pill → (2) response text 14px/1.6 → (3) footer: `⊞ N sources` + latency in DM Mono → (4) feedback row: 👍 👎.

**Never** wrap AI response in a card/bubble.

### KB Hint

```
"SharePoint · Google Drive · 2,081 documents indexed"   ✅
"RAG · SharePoint + Google Drive · 2,081 docs"          ❌ — never show internal labels to end users
```

11px, `color: var(--text-faint)`, accent dot indicator. Lives below input in empty state only.

### Admin Table

```css
th — 11px, uppercase, letter-spacing .05em, --text-faint
td — 13px, vertical-align middle, padding 12px 14px
row hover — background: var(--accent-dim)
```

Numbers/IDs/dates/percentages in **DM Mono**. Names/labels in **Plus Jakarta Sans** weight 500.

### Tab Navigation

```css
.admin-tab {
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-faint);
  border-bottom: 2px solid transparent;
}
.admin-tab.active {
  color: var(--text-primary);
  border-bottom-color: var(--accent);
}
.admin-tabs {
  border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
```

### Slide-In Detail Panel

Slides from right. Header: name + status badge + × close. Sections: Identity → Metrics → Quick Actions. Destructive actions (Suspend, Delete) in `--alert`, placed last, visually separated.

### Wizard / Step Modal

`max-width: 640px`, `border-radius: var(--r-lg)`. Progress bar top (accent fill). "Step N of M" label. Footer: [← Back] ghost + [Next →] primary. × in top-right dismisses.

### Severity & Status Colors

| State           | Color                |
| --------------- | -------------------- |
| P0              | `#FF3547` red        |
| P1              | `--alert` orange     |
| P2              | `--warn` yellow      |
| P3/P4           | `--bg-elevated` grey |
| Active/Healthy  | `--accent` green     |
| At Risk         | `--warn` yellow      |
| Suspended/Error | `--alert` orange     |

Health score: ≥70 → accent · 50-69 → warn · <50 → alert.

### Scrollbars

```css
::-webkit-scrollbar {
  width: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 2px;
}
```

### Transitions & Animation

```css
--t:
  background 220ms ease, color 220ms ease, border-color 220ms ease,
  box-shadow 220ms ease;
/* Screen transitions: fadeIn 260ms ease */
/* No heavy animations — information density is high */
```

---

## Layout Architecture (Three-Role Screen Map)

### End User

- Sidebar: **History only** (no agent list, no routing navigation)
- Main: two-state chat (empty-centered / active-bottom-fixed)
- Right panel: source citations (slides in)
- Mode selector in input bar controls agent routing (Auto / Finance / HR / Legal…)
- Registry (Discover / My Agents / Transactions) — RBAC-gated, not in default sidebar

### Tenant Admin

- Sidebar sections: **Workspace** | **Insights**
- Nav items: Dashboard · Documents · Users · Agents · Glossary | Analytics · Issues · Settings
- Screen switching: `showTAPanel(name)` — panels named `ta-panel-{name}`
- New screens MUST use `ta-panel-{name}` naming and `showTAPanel()` pattern

### Platform Admin

- Sidebar sections: **Operations** | **Intelligence** | **Finance**
- Nav items: Dashboard · Tenants · Issue Queue | LLM Profiles · Agent Templates · Analytics · Tool Catalog | Cost Analytics
- Drill-down: slide-in detail panels (not new routes)
- Complex actions: wizard modals (New Tenant, Onboarding)
- New screens MUST use slide-in panel pattern for detail views; modals for multi-step wizards

**Rule**: Never invent a new layout pattern. Match the existing panel/modal/tab pattern for the role.

---

## Banned Patterns

- `#6366F1`, `#8B5CF6`, `#3B82F6` — purple/blue palette (AI slop tell)
- Inter, Roboto — wrong typeface
- Purple-to-blue gradients, neon-on-dark accents
- Glassmorphism on any surface
- `shadow-lg` on every card
- `transition-all 300ms` blanket transitions
- `rounded-2xl` uniform radius
- Gradient text
- AI response in a card/bubble with background fill
- "Workspaces" label in end-user sidebar (correct: History only)
- Raw "RAG ·" in KB hints visible to end users

---

## Design Principles (1-line each)

1. **Data before decoration** — numbers and status signals are always the most prominent element.
2. **Single accent** — `#4FFFB0` is a signal, not wallpaper. Use sparingly and meaningfully.
3. **Dark by default** — dark is the primary experience; light and system are alternatives.
4. **Density without clutter** — every row, card, and column earns its place.
5. **Role clarity** — End User / Tenant Admin / Platform Admin never share a layout.
6. **Confidence through typography** — DM Mono for data values; mixing body font into data erodes trust.
