# 07 — Obsidian Intelligence Design System

**Reference**: `workspaces/mingai/design/01-design-language.md` (source of truth)
**Prototype**: `workspaces/mingai/99-ui-proto/index.html` (visual reference)

This file is the implementation reference. For any conflict with product documentation, product documentation wins.

---

## Design Tokens

### Color Palette

```css
/* Background layers (darkest to lightest) */
--bg-base: #0c0e14; /* Page background */
--bg-surface: #12141c; /* Card backgrounds */
--bg-elevated: #1a1d28; /* Elevated panels, modals */
--bg-overlay: #22263a; /* Tooltips, dropdowns */

/* Borders */
--border-subtle: #2a2e42; /* Dividers, inactive */
--border-default: #353a52; /* Card borders, inputs */
--border-focus: #4fffb0; /* Focus rings */

/* Typography */
--text-primary: #f0f2ff; /* Main content */
--text-secondary: #a8aeca; /* Labels, captions */
--text-muted: #6b7299; /* Placeholders, hints */
--text-disabled: #3d4266; /* Disabled states */

/* Accent */
--accent: #4fffb0; /* CTAs, active states, accent text */
--accent-dim: #2dd68a; /* Hover on accent */
--accent-glow: rgba(79, 255, 176, 0.15); /* Glow effects */

/* Semantic */
--error: #ff4f6b;
--warning: #ffb84f;
--success: #4fffb0; /* Same as accent */
--info: #4f9fff;
```

### Border Radius

```css
--r: 7px; /* Controls: buttons, inputs, chips */
--r-lg: 10px; /* Cards, panels */
--r-sm: 4px; /* Badges, tags */
--r-full: 9999px; /* Pills */
```

### Typography

```css
/* Display + Body: Plus Jakarta Sans */
font-family: "Plus Jakarta Sans", system-ui, sans-serif;

/* Data + Numbers + Code: DM Mono */
font-family: "DM Mono", "Courier New", monospace;
```

Font loading (in `app/layout.tsx`):

```typescript
import { Plus_Jakarta_Sans, DM_Mono } from "next/font/google";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  weight: ["400", "500", "600", "700"],
});

const dmMono = DM_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
});
```

### Spacing Scale

```css
4px  → gap-1
8px  → gap-2
12px → gap-3
16px → gap-4
20px → gap-5
24px → gap-6
32px → gap-8
40px → gap-10
48px → gap-12
```

---

## Component Specifications

### Buttons

```tsx
// Primary CTA
<button className="
  bg-accent text-bg-base font-semibold
  px-4 py-2 rounded-control
  hover:bg-accent-dim
  transition-colors
">
  Provision Tenant
</button>

// Secondary (ghost)
<button className="
  border border-border-default text-text-primary
  px-4 py-2 rounded-control
  hover:bg-bg-elevated
  transition-colors
">
  Cancel
</button>

// Destructive
<button className="
  border border-error text-error
  px-4 py-2 rounded-control
  hover:bg-error/10
  transition-colors
">
  Delete
</button>
```

### Cards

```tsx
<div
  className="
  bg-bg-surface border border-border-default
  rounded-card p-6
"
>
  {/* Card content */}
</div>
```

### Badges / Status Pills

```tsx
// Status badge
const statusColor = {
  active: "text-accent border-accent/30 bg-accent/10",
  suspended: "text-warning border-warning/30 bg-warning/10",
  error: "text-error border-error/30 bg-error/10",
};

<span className={`
  text-xs font-medium px-2 py-0.5
  rounded-badge border
  ${statusColor[status]}
`}>
  {status}
</span>

// Source badge (memory notes)
<span className="
  text-xs text-text-muted
  border border-border-subtle
  rounded-badge px-2 py-0.5
">
  user-directed  {/* or: auto-extracted */}
</span>
```

### Filter Chips (Outlined — NOT Filled Accent)

```tsx
// CORRECT: outlined neutral
<button className={`
  text-sm px-3 py-1.5 rounded-control
  border transition-colors
  ${active
    ? "border-accent text-accent bg-accent/10"
    : "border-border-default text-text-secondary hover:border-border-focus"
  }
`}>
  {label}
</button>

// WRONG: filled accent — do not use for filter chips
<button className="bg-accent text-bg-base ...">All Agents</button>
```

### Input Fields

```tsx
<input
  className="
  w-full bg-bg-elevated border border-border-default
  rounded-control px-3 py-2
  text-text-primary placeholder:text-text-muted
  focus:outline-none focus:border-border-focus focus:ring-1 focus:ring-accent/20
  transition-colors
"
/>
```

### Tables (via Shadcn/UI + TanStack Table)

```tsx
// Header row
<th className="
  text-xs font-medium text-text-muted uppercase tracking-wider
  px-4 py-3 text-left
  border-b border-border-subtle
" />

// Data row
<tr className="
  border-b border-border-subtle
  hover:bg-bg-elevated transition-colors
" />

// Data cell
<td className="px-4 py-3 text-sm text-text-primary" />
```

---

## Layout Patterns

### App Shell

```
┌─────────────────────────────────────┐
│ Topbar (56px)                       │
├──────────┬──────────────────────────┤
│ Sidebar  │ Main Content             │
│ (240px)  │                          │
│          │                          │
│          │                          │
└──────────┴──────────────────────────┘
```

Sidebar: `bg-bg-surface border-r border-border-subtle`
Topbar: `bg-bg-surface border-b border-border-subtle h-14`

### Chat Layout — Two States

**Empty state** (no messages yet):

```
┌────────────────────────────┐
│          [Logo]            │
│                            │
│    ┌──────────────────┐    │
│    │  Ask anything... │    │  ← centered input
│    └──────────────────┘    │
│                            │
│  SharePoint · 2,081 docs   │  ← KB hint (NOT "RAG ·")
└────────────────────────────┘
```

**Active state** (after first message):

```
┌────────────────────────────┐
│ [Source Panel]   [Messages]│
│                            │
│                            │
│                            │
├────────────────────────────┤
│ ┌──────────────────────┐   │  ← bottom-fixed input
│ │  Ask follow-up...    │   │
│ └──────────────────────┘   │
└────────────────────────────┘
```

### Sidebar Navigation (Role-Aware)

```tsx
// End User sidebar
const END_USER_NAV = [
  { label: "Agents", icon: BotIcon, href: "/agents" }, // "Agents" NOT "Workspaces"
  { label: "Chat", icon: MessageIcon, href: "/chat" },
  { label: "Privacy", icon: ShieldIcon, href: "/settings/privacy" },
];

// Tenant Admin sidebar (additional items)
const TENANT_ADMIN_NAV = [
  ...END_USER_NAV,
  { label: "Workspace", icon: SettingsIcon, href: "/settings/workspace" },
  { label: "Users", icon: UsersIcon, href: "/settings/users" },
  {
    label: "Knowledge Base",
    icon: DatabaseIcon,
    href: "/settings/knowledge-base",
  },
  { label: "Glossary", icon: BookIcon, href: "/settings/glossary" },
  { label: "Agents", icon: BotIcon, href: "/settings/agents" },
  { label: "Teams", icon: TeamIcon, href: "/settings/teams" },
  { label: "Memory Policy", icon: BrainIcon, href: "/settings/memory-policy" },
  { label: "Analytics", icon: ChartIcon, href: "/settings/analytics" },
];

// Platform Admin sidebar (separate shell)
const PLATFORM_ADMIN_NAV = [
  { label: "Tenants", icon: BuildingIcon, href: "/admin/tenants" },
  { label: "LLM Profiles", icon: CpuIcon, href: "/admin/llm-profiles" },
  { label: "Cost Analytics", icon: DollarIcon, href: "/admin/cost-analytics" },
  { label: "Issue Queue", icon: AlertIcon, href: "/admin/issue-queue" },
];
```

---

## Data Display

### Numbers + Metrics (DM Mono)

```tsx
// Token counts, scores, percentages — always DM Mono
<span className="font-mono text-text-primary">1,234,567</span>
<span className="font-mono text-accent">87%</span>
```

### Confidence Visualization

```tsx
// Retrieval confidence — bar + percentage
// Label MUST be "retrieval confidence"
<div className="flex items-center gap-2">
  <span className="text-xs text-text-secondary">retrieval confidence</span>
  <div className="h-1.5 w-20 rounded-full bg-bg-overlay">
    <div
      className="h-full rounded-full bg-accent"
      style={{ width: `${Math.round(score * 100)}%` }}
    />
  </div>
  <span className="font-mono text-xs text-text-primary">
    {Math.round(score * 100)}%
  </span>
</div>
```

### Source Citations

```tsx
<div className="flex flex-col gap-2">
  {sources.map((source) => (
    <div
      key={source.id}
      className="
      bg-bg-elevated border border-border-subtle
      rounded-control p-3
    "
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-primary">
          {source.title}
        </span>
        <span className="font-mono text-xs text-accent">
          {Math.round(source.score * 100)}%
        </span>
      </div>
      <p className="text-xs text-text-muted mt-1 line-clamp-2">
        {source.excerpt}
      </p>
    </div>
  ))}
</div>
```

---

## Prohibited Patterns

```tsx
// WRONG: "Workspaces" instead of "Agents"
<SidebarItem label="Workspaces" />

// CORRECT
<SidebarItem label="Agents" />

// WRONG: "RAG" or technical terms in KB hint
<span>RAG · 2,081 chunks</span>

// CORRECT
<span>SharePoint · Google Drive · 2,081 documents indexed</span>

// WRONG: Filled accent for filter chips
<button className="bg-accent text-bg-base">HR Policy</button>

// CORRECT: Outlined neutral for filter chips
<button className="border border-border-default text-text-secondary">HR Policy</button>

// WRONG: "AI confidence" or "answer quality" label
<span>AI confidence: 87%</span>

// CORRECT
<span>retrieval confidence: 87%</span>

// WRONG: raw innerHTML without sanitization
<div dangerouslySetInnerHTML={{ __html: userContent }} />

// CORRECT
<SafeHTML html={userContent} />
```

---

## Loading States

```tsx
// Skeleton loader for cards
<div className="animate-pulse space-y-3">
  <div className="h-4 bg-bg-elevated rounded w-3/4" />
  <div className="h-4 bg-bg-elevated rounded w-1/2" />
</div>

// Streaming cursor (chat)
<span className="inline-block w-2 h-4 bg-accent animate-pulse ml-0.5" />

// Status indicator (provisioning)
<div className="flex items-center gap-2 text-sm text-text-secondary">
  <div className="h-2 w-2 rounded-full bg-accent animate-pulse" />
  <span>{statusMessage}</span>
</div>
```

---

## Shadcn/UI Component Configuration

Initialize with dark theme matching Obsidian Intelligence:

```bash
npx shadcn@latest init
# Select: dark, CSS variables, tailwind, app router
```

`components.json`:

```json
{
  "style": "default",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "app/globals.css",
    "baseColor": "slate",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils"
  }
}
```

Override Shadcn CSS variables to match Obsidian tokens:

```css
/* app/globals.css */
@layer base {
  :root {
    --background: 218 21% 7%; /* #0C0E14 */
    --foreground: 230 60% 95%; /* #F0F2FF */
    --card: 225 22% 9%; /* #12141C */
    --card-foreground: 230 60% 95%;
    --primary: 154 100% 75%; /* #4FFFB0 */
    --primary-foreground: 218 21% 7%;
    --border: 228 24% 22%; /* #2A2E42 */
    --input: 228 24% 22%;
    --ring: 154 100% 75%;
    --radius: 0.4375rem; /* 7px */
  }
}
```
