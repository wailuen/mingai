# 03 — Frontend (Web) Implementation Guide

**Worktree**: web
**Branch**: `feat/phase-1-web`
**Framework**: Next.js 14 (App Router) + TypeScript + Shadcn/UI
**Port**: 3022
**Design System**: Obsidian Intelligence (see `07-design-system.md`)

Read `01-context-loading.md` before starting. Read `07-design-system.md` before building ANY component.

---

## Project Setup

```bash
npx create-next-app@14 src/web --typescript --tailwind --app --no-src-dir
cd src/web

# Install component library
npx shadcn@latest init  # select: dark theme, CSS variables, tailwind

# Core dependencies
npm install @tanstack/react-table recharts lucide-react
npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu
npm install @radix-ui/react-select @radix-ui/react-toast
npm install dompurify @types/dompurify  # XSS protection (FE-062)
npm install @auth0/nextjs-auth0         # Phase 2

# Dev dependencies
npm install -D @playwright/test
npx playwright install
```

### Tailwind Configuration

`tailwind.config.ts` — extend with Obsidian Intelligence tokens:

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-base": "#0C0E14",
        "bg-surface": "#12141C",
        "bg-elevated": "#1A1D28",
        "bg-overlay": "#22263A",
        "border-subtle": "#2A2E42",
        "border-default": "#353A52",
        "text-primary": "#F0F2FF",
        "text-secondary": "#A8AECA",
        "text-muted": "#6B7299",
        "text-disabled": "#3D4266",
        accent: "#4FFFB0",
        "accent-dim": "#2DD68A",
        "accent-glow": "rgba(79, 255, 176, 0.15)",
        error: "#FF4F6B",
        warning: "#FFB84F",
        info: "#4F9FFF",
      },
      borderRadius: {
        control: "7px",
        card: "10px",
        badge: "4px",
      },
      fontFamily: {
        sans: ["Plus Jakarta Sans", "system-ui", "sans-serif"],
        mono: ["DM Mono", "Courier New", "monospace"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
```

---

## Directory Structure

```
src/web/
├── app/
│   ├── layout.tsx                      # Root layout (fonts, providers)
│   ├── page.tsx                        # Redirect → /chat or /login
│   ├── login/page.tsx                  # Login page
│   ├── chat/                           # End user chat
│   │   ├── page.tsx                    # Chat interface (empty state)
│   │   └── [conversationId]/page.tsx   # Active chat
│   ├── agents/page.tsx                 # Agent selection (sidebar)
│   ├── settings/                       # Tenant admin + user settings
│   │   ├── layout.tsx                  # Settings shell
│   │   ├── workspace/page.tsx          # Workspace config
│   │   ├── users/page.tsx              # User management
│   │   ├── knowledge-base/page.tsx     # SharePoint + Google Drive
│   │   ├── glossary/page.tsx           # Glossary management
│   │   ├── agents/page.tsx             # Agent management
│   │   ├── teams/page.tsx              # Team management
│   │   ├── memory-policy/page.tsx      # Memory settings
│   │   ├── analytics/page.tsx          # Usage analytics
│   │   └── privacy/page.tsx            # My privacy settings (end user)
│   ├── admin/                          # Platform admin
│   │   ├── layout.tsx                  # Platform admin shell
│   │   ├── tenants/page.tsx            # Tenant list
│   │   ├── tenants/new/page.tsx        # Provision wizard
│   │   ├── tenants/[id]/page.tsx       # Tenant detail
│   │   ├── llm-profiles/page.tsx       # LLM profile management
│   │   ├── cost-analytics/page.tsx     # Cross-tenant costs
│   │   └── issue-queue/page.tsx        # Platform issue queue
│   └── registry/                       # Hosted Agent Registry (Phase 2)
│       ├── page.tsx                    # Discover agents
│       ├── my-agents/page.tsx          # My published agents
│       └── transactions/page.tsx       # Transaction history
├── components/
│   ├── ui/                             # Shadcn/UI base components (auto-generated)
│   ├── chat/
│   │   ├── ChatInterface.tsx           # Root chat component (2 states)
│   │   ├── ChatEmptyState.tsx          # Centered input, agent context
│   │   ├── ChatActiveState.tsx         # Bottom-fixed input + messages
│   │   ├── MessageBubble.tsx           # User + assistant messages
│   │   ├── SourcePanel.tsx             # Source citations with confidence
│   │   ├── FeedbackButtons.tsx         # Thumbs up/down
│   │   ├── StreamingResponse.tsx       # SSE token streaming
│   │   ├── GlossaryExpansionIndicator.tsx  # "Terms interpreted" (mandatory)
│   │   ├── ProfileIndicator.tsx        # "Profile used" badge
│   │   └── TeamContextBadge.tsx        # "Using Finance Team context"
│   ├── memory/
│   │   ├── MemoryNotesList.tsx         # Notes list with source badge + delete
│   │   ├── PrivacyDisclosureDialog.tsx # First-use transparency (NOT consent gate)
│   │   └── MemorySourceBadge.tsx       # "user-directed" | "auto-extracted"
│   ├── admin/
│   │   ├── TenantTable.tsx             # TanStack Table: paginated tenant list
│   │   ├── ProvisioningWizard.tsx      # 4-step tenant creation
│   │   ├── UserTable.tsx               # TanStack Table: user directory
│   │   ├── TeamManagement.tsx          # Team CRUD + Auth0 sync controls
│   │   ├── GlossaryTable.tsx           # Glossary CRUD + CSV import
│   │   └── LLMProfileSelector.tsx      # Select from published profiles
│   ├── layout/
│   │   ├── Sidebar.tsx                 # Role-aware sidebar navigation
│   │   ├── Topbar.tsx                  # Role switcher (dev) + user menu
│   │   └── RoleGuard.tsx              # Client-side role check wrapper
│   └── shared/
│       ├── SafeHTML.tsx                # DOMPurify wrapper (FE-062)
│       ├── ErrorBoundary.tsx           # React Error Boundary (FE-063)
│       ├── LoadingState.tsx            # Skeleton loaders
│       └── ConfidenceBar.tsx           # Retrieval confidence visualization
├── hooks/
│   ├── useChat.ts                      # Chat SSE + conversation state
│   ├── useUserMemory.ts                # Memory notes CRUD
│   ├── useProfile.ts                   # User profile read/update
│   └── useAuth.ts                      # Auth token management
├── lib/
│   ├── api.ts                          # API client
│   ├── sse.ts                          # SSE stream parser
│   ├── auth.ts                         # JWT/Auth0 helpers
│   └── sanitize.ts                     # DOMPurify wrapper
├── middleware.ts                        # Next.js route protection
└── tests/                              # Playwright E2E
```

---

## Auth Integration

### Phase 1: JWT (local dev)

`lib/auth.ts`:

```typescript
import { jwtDecode } from "jwt-decode";

interface JWTClaims {
  sub: string;
  tenant_id: string;
  roles: string[];
  scope: "platform" | "tenant";
  plan: string;
  exp: number;
}

export function getStoredToken(): string | null {
  // Phase 1: token stored in a regular (non-httpOnly) cookie for client-side access.
  // Phase 2 (Auth0): switch to httpOnly cookies — tokens sent automatically by browser
  // and never read via JS. Remove this function in Phase 2 and rely on Auth0 SDK.
  // NEVER store tokens in localStorage (vulnerable to XSS).
  return (
    document.cookie
      .split("; ")
      .find((row) => row.startsWith("access_token="))
      ?.split("=")[1] ?? null
  );
}

export function decodeToken(token: string): JWTClaims {
  return jwtDecode<JWTClaims>(token);
}

export function isTokenExpired(token: string): boolean {
  const claims = decodeToken(token);
  return claims.exp * 1000 < Date.now();
}
```

### Phase 2: Auth0

```typescript
// lib/auth0.ts
import { Auth0Client } from "@auth0/nextjs-auth0";

export const auth0 = new Auth0Client({
  domain: process.env.AUTH0_DOMAIN!,
  clientId: process.env.AUTH0_CLIENT_ID!,
  clientSecret: process.env.AUTH0_CLIENT_SECRET!,
  audience: process.env.AUTH0_AUDIENCE!,
  baseURL: process.env.AUTH0_BASE_URL!,
});
```

### Route Middleware

`middleware.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { decodeToken, isTokenExpired } from "@/lib/auth";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("access_token")?.value;

  // Redirect to login if no token
  if (!token || isTokenExpired(token)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const claims = decodeToken(token);

  // Platform admin routes: require scope=platform
  if (request.nextUrl.pathname.startsWith("/admin")) {
    if (claims.scope !== "platform") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Settings routes: require tenant admin role
  if (
    request.nextUrl.pathname.startsWith("/settings/workspace") ||
    request.nextUrl.pathname.startsWith("/settings/users")
  ) {
    if (!claims.roles.includes("tenant_admin")) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/chat/:path*", "/admin/:path*", "/settings/:path*"],
};
```

---

## API Client

`lib/api.ts`:

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL;

interface ApiError {
  error: string;
  message: string;
  request_id: string;
}

class ApiException extends Error {
  constructor(
    public status: number,
    public body: ApiError,
  ) {
    super(body.message);
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const error: ApiError = await res.json();
    throw new ApiException(res.status, error);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}
```

---

## SSE Chat Streaming

`lib/sse.ts`:

```typescript
export type SSEEvent =
  | { type: "status"; data: { stage: string; message: string } }
  | { type: "sources"; data: { sources: Source[] } }
  | { type: "response_chunk"; data: { text: string } }
  | {
      type: "metadata";
      data: {
        retrieval_confidence: number;
        tokens_used: number;
        glossary_expansions: string[];
      };
    }
  | { type: "memory_saved"; data: { note_id: string } }
  | { type: "profile_context_used"; data: { layers_active: string[] } }
  | { type: "done"; data: { conversation_id: string; message_id: string } }
  | { type: "error"; data: { code: string; message: string } };

export async function* streamChat(
  query: string,
  conversationId: string | null,
  agentId: string,
  token: string,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
      agent_id: agentId,
    }),
  });

  if (!response.ok) throw new Error("Chat request failed");

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        const eventType = line.slice(7).trim();
        const dataLine = lines[lines.indexOf(line) + 1];
        if (dataLine?.startsWith("data: ")) {
          const data = JSON.parse(dataLine.slice(6));
          yield { type: eventType, data } as SSEEvent;
        }
      }
    }
  }
}
```

`hooks/useChat.ts`:

```typescript
import { useState, useCallback } from "react";
import { streamChat, SSEEvent } from "@/lib/sse";
import { useAuth } from "@/hooks/useAuth";

export function useChat(agentId: string) {
  const { token } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [retrievalConfidence, setRetrievalConfidence] = useState<number | null>(
    null,
  );
  const [glossaryExpansions, setGlossaryExpansions] = useState<string[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (query: string) => {
      setStreaming(true);
      let assistantText = "";

      try {
        for await (const event of streamChat(
          query,
          conversationId,
          agentId,
          token,
        )) {
          switch (event.type) {
            case "sources":
              setSources(event.data.sources);
              break;
            case "response_chunk":
              assistantText += event.data.text;
              setMessages((prev) =>
                updateLastAssistantMessage(prev, assistantText),
              );
              break;
            case "metadata":
              setRetrievalConfidence(event.data.retrieval_confidence);
              setGlossaryExpansions(event.data.glossary_expansions ?? []);
              break;
            case "done":
              setConversationId(event.data.conversation_id);
              break;
          }
        }
      } finally {
        setStreaming(false);
      }
    },
    [token, agentId, conversationId],
  );

  return {
    messages,
    streaming,
    sources,
    retrievalConfidence,
    glossaryExpansions,
    sendMessage,
  };
}
```

---

## Chat Interface — Two-State Layout

`components/chat/ChatInterface.tsx`:

```tsx
"use client";
import { useState } from "react";
import { ChatEmptyState } from "./ChatEmptyState";
import { ChatActiveState } from "./ChatActiveState";
import { useChat } from "@/hooks/useChat";

interface ChatInterfaceProps {
  agentId: string;
}

export function ChatInterface({ agentId }: ChatInterfaceProps) {
  const {
    messages,
    streaming,
    sources,
    retrievalConfidence,
    glossaryExpansions,
    sendMessage,
  } = useChat(agentId);
  const hasMessages = messages.length > 0;

  return (
    <div className="h-full flex flex-col bg-bg-base">
      {hasMessages ? (
        <ChatActiveState
          messages={messages}
          streaming={streaming}
          sources={sources}
          retrievalConfidence={retrievalConfidence}
          glossaryExpansions={glossaryExpansions}
          onSend={sendMessage}
        />
      ) : (
        <ChatEmptyState onSend={sendMessage} agentId={agentId} />
      )}
    </div>
  );
}
```

### Glossary Expansion Indicator (Mandatory)

```tsx
// components/chat/GlossaryExpansionIndicator.tsx
// MANDATORY: Show on every response with ≥1 expansion

interface Props {
  expansions: string[]; // e.g., ["AWS → Annual Wage Supplement"]
}

export function GlossaryExpansionIndicator({ expansions }: Props) {
  if (expansions.length === 0) return null;

  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-text-muted">
      <span className="rounded-badge border border-border-subtle px-2 py-0.5">
        Terms interpreted
      </span>
      <span>{expansions.slice(0, 3).join(" · ")}</span>
      {expansions.length > 3 && (
        <button className="underline">+{expansions.length - 3} more</button>
      )}
    </div>
  );
}
```

### Retrieval Confidence Display

```tsx
// components/shared/ConfidenceBar.tsx
// Label MUST be "retrieval confidence" — never "AI confidence" or "answer quality"

interface Props {
  score: number; // 0.0 to 1.0
}

export function ConfidenceBar({ score }: Props) {
  const pct = Math.round(score * 100);
  const color =
    score >= 0.8 ? "bg-accent" : score >= 0.6 ? "bg-warning" : "bg-error";

  return (
    <div className="flex items-center gap-2 text-xs text-text-secondary">
      <span>retrieval confidence</span>
      <div className="h-1.5 w-20 rounded-full bg-bg-overlay">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-text-primary">{pct}%</span>
    </div>
  );
}
```

---

## Privacy Settings (End User)

`app/settings/privacy/page.tsx` — port from aihub2 with these changes:

1. `PrivacyDisclosureDialog` shown on first profile use:
   - Explains what is collected (queries, org context, working memory)
   - Provides right-to-object control
   - NOT a consent gate — transparency only
   - Set `profile_disclosure_shown` cookie after display

2. Memory Notes list (`MemoryNotesList.tsx`):
   - Show source badge: `user-directed` | `auto-extracted`
   - Delete individual notes
   - "Clear all" button (confirmation dialog)

3. Org context toggles:
   - Master toggle: "Use org context in responses"
   - Sub-toggle: "Include manager name"
   - Both write to `user_profiles.org_context_enabled` / `share_manager_info`

---

## Tenant Admin Pages

### Users (`/settings/users`)

```tsx
// Key requirements (from FE-041 through FE-045):
// - TanStack Table with server-side pagination (NOT client-side)
// - Invite: single email OR CSV upload (FE-044)
// - Role change takes effect immediately (warn user)
// - RBAC enforced at query time NOT assignment time (from canonical spec)
// - Delete = anonymize (not hard delete) per GDPR

import { useReactTable, getCoreRowModel } from "@tanstack/react-table";

export function UserTable({ tenantId }: { tenantId: string }) {
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 25 });
  const { data } = useQuery(["users", pagination], () =>
    apiRequest(
      `/api/v1/users?page=${pagination.pageIndex}&limit=${pagination.pageSize}`,
    ),
  );

  // TanStack Table setup
  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    pageCount: data?.total_pages ?? -1,
    state: { pagination },
    onPaginationChange: setPagination,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
  });
  // ...
}
```

### Teams (`/settings/teams`)

Key requirements (from Plan 10):

- List teams with source badge: `manual` | `auth0-synced`
- Create/edit/archive teams
- Add/remove members
- Auth0 sync settings: enable/disable, configure allowlist
- Allowlist: empty by default (no auto-sync until configured)
- Auth0-synced records cannot be overwritten by manual records
- Membership audit log visible per team

### Memory Policy (`/settings/memory-policy`)

Tenant admin controls:

- Profile learning: enabled / disabled (master toggle)
- Working memory TTL: slider 1-30 days (default 7)
- Memory notes max: slider 5-50 (default 15)
- Allow auto-extracted notes: toggle
- Org context: enabled / disabled
- Profile learning trigger: slider 5-25 queries (default 10)

---

## Platform Admin Pages

### Tenant Provisioning Wizard (`/admin/tenants/new`)

4-step wizard:

1. Basic Info: name, primary contact email, plan tier
2. LLM Profile: select from GET /api/v1/admin/llm-profiles
3. Quotas: monthly token limit, rate limit
4. Review + Provision → POST /api/v1/admin/tenants (async)
   - Show job status via SSE: GET /api/v1/admin/provisioning/{job_id}
   - < 10 minute SLA for full provisioning

### Platform Admin Bootstrap (INFRA-066)

First-time setup: if no platform admin user exists, show setup wizard at `/admin/bootstrap`:

- Create platform admin account
- Set JWT secret
- Configure first LLM profile
- Create seed tenant for testing

---

## XSS Protection (FE-062)

`components/shared/SafeHTML.tsx`:

```tsx
import DOMPurify from "dompurify";

interface Props {
  html: string;
  className?: string;
}

export function SafeHTML({ html, className }: Props) {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "strong", "em", "ul", "ol", "li", "br", "code", "pre"],
    ALLOWED_ATTR: [],
  });

  return (
    <div className={className} dangerouslySetInnerHTML={{ __html: clean }} />
  );
}
```

**Rule**: NEVER use raw `dangerouslySetInnerHTML` — always through `SafeHTML`.

---

## Error Boundaries (FE-063)

`components/shared/ErrorBoundary.tsx`:

```tsx
"use client";
import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error("ErrorBoundary caught:", error, info);
    // Send to error tracking (Sentry, etc.)
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="p-6 text-error">
            Something went wrong. Please refresh the page.
          </div>
        )
      );
    }
    return this.props.children;
  }
}
```

Wrap every major UI section:

```tsx
// In app/chat/page.tsx
<ErrorBoundary fallback={<ChatErrorState />}>
  <ChatInterface agentId={agentId} />
</ErrorBoundary>
```

---

## Knowledge Base Display

The knowledge base hint in the chat empty state:

```tsx
// CORRECT
<span className="text-text-muted">SharePoint · Google Drive · 2,081 documents indexed</span>

// WRONG — never expose implementation details
<span>RAG · Vector search · 2,081 chunks</span>
```

Sidebar agent label:

```tsx
// CORRECT
<SidebarSection title="Agents" />

// WRONG
<SidebarSection title="Workspaces" />
```

---

## Running the Frontend

```bash
cd src/web
npm run dev   # port 3022
npm run build # production build
npx playwright test  # E2E tests (requires backend running)
```
