# Frontend Architecture (Next.js 14)

## Tech Stack

| Layer                | Technology                   | Purpose                      |
| -------------------- | ---------------------------- | ---------------------------- |
| **Framework**        | Next.js 14                   | React framework with SSR     |
| **Language**         | TypeScript 5.3               | Type-safe development        |
| **Styling**          | TailwindCSS 3                | Utility-first CSS            |
| **Components**       | shadcn/ui                    | Accessible component library |
| **State Management** | TanStack Query (React Query) | Server-side state            |
| **Real-Time**        | WebSocket + SSE              | Server push notifications    |
| **HTTP Client**      | Fetch API + axios            | HTTP requests                |
| **Testing**          | Vitest + Playwright          | Unit & E2E testing           |

---

## App Structure (Next.js 14 App Router)

```
src/frontend/src/
├── app/                          # App Router (Next.js 14)
│   ├── layout.tsx                # Root layout
│   ├── page.tsx                  # Home page
│   ├── auth/
│   │   ├── login/page.tsx
│   │   ├── callback/page.tsx     # OAuth callback
│   │   └── logout/page.tsx
│   ├── chat/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # Chat main view
│   │   ├── [conversation_id]/page.tsx
│   │   └── new/page.tsx
│   ├── admin/
│   │   ├── users/page.tsx
│   │   ├── roles/page.tsx
│   │   └── indexes/page.tsx
│   └── settings/
│       └── page.tsx
│
├── components/                   # Reusable React components
│   ├── auth/
│   │   ├── LoginButton.tsx
│   │   └── AuthGuard.tsx         # Wrapper for protected routes
│   ├── chat/
│   │   ├── ChatInterface.tsx     # Main chat UI
│   │   ├── MessageList.tsx       # Display messages
│   │   ├── InputArea.tsx         # User input box
│   │   ├── SourcePanel.tsx       # Show retrieved sources
│   │   └── ConfidenceBadge.tsx  # Confidence score display
│   ├── common/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   ├── Footer.tsx
│   │   └── ErrorBoundary.tsx
│   └── admin/
│       ├── UserTable.tsx
│       ├── RoleManager.tsx
│       └── IndexConfig.tsx
│
├── hooks/                        # Custom React hooks
│   ├── useAuth.ts               # Auth context & functions
│   ├── useChat.ts               # Chat conversation logic
│   ├── useWebSocket.ts          # WebSocket connection
│   ├── useSSE.ts                # Server-Sent Events
│   └── useApi.ts                # API wrapper
│
├── lib/                          # Utility functions
│   ├── api.ts                   # API client factory
│   ├── auth.ts                  # Auth utilities
│   ├── sseClient.ts             # SSE event handling
│   ├── websocket.ts             # WebSocket wrapper
│   └── queryClient.ts           # React Query config
│
├── contexts/                     # React Context
│   ├── AuthContext.tsx          # User auth state
│   ├── ChatContext.tsx          # Chat state
│   └── NotificationContext.tsx  # Toast notifications
│
├── types/                        # TypeScript types
│   ├── auth.ts
│   ├── chat.ts
│   ├── api.ts
│   └── index.ts                 # Type exports
│
└── styles/                       # Global styles
    ├── globals.css              # TailwindCSS imports
    └── variables.css            # CSS variables
```

---

## Key Pages

### Login Page (`/auth/login`)

```typescript
// Components: Azure AD SSO button + Local login form
- Display Microsoft login button
- On click: Redirect to Azure AD OAuth endpoint
- Fallback: Local email/password form (dev only)
```

### Chat Page (`/chat`)

```typescript
// Main chat interface
- Layout:
  - Header: Logo, user profile, notifications
  - Sidebar: Conversation history, new conversation, admin links
  - Main: ChatInterface component
  - Right panel: Sources, metadata, feedback

- Components:
  - ChatInterface: Message list + input area
  - MessageList: Display sent/received messages, sources
  - InputArea: Text input, submit button, MCP tool selection
  - SourcePanel: Show retrieved documents with scores
  - ConfidenceBadge: Display confidence level
```

### Admin Pages (`/admin/*`)

- **Users** (`/admin/users`): List, search, create, delete, assign roles
- **Roles** (`/admin/roles`): Create, edit, delete, manage permissions
- **Indexes** (`/admin/indexes`): Register, configure, sync, statistics

---

## State Management (React Query)

### Custom Hooks

```typescript
// useAuth.ts - Authentication
const useAuth = () => {
  const query = useQuery({
    queryKey: ["auth", "current"],
    queryFn: () => api.get("/api/v1/auth/current"),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  return {
    user: query.data,
    isLoading: query.isLoading,
    isAuthenticated: !!query.data,
    logout: () => api.post("/api/v1/auth/logout"),
  };
};

// useChat.ts - Chat operations
const useChat = (conversationId: string) => {
  const query = useQuery({
    queryKey: ["chat", "messages", conversationId],
    queryFn: () => api.get(`/api/v1/conversations/${conversationId}/messages`),
    enabled: !!conversationId,
  });

  const mutation = useMutation({
    mutationFn: (query: string) =>
      api.post(`/api/v1/chat/stream`, { query, conversationId }),
    onSuccess: () => query.refetch(),
  });

  return {
    messages: query.data,
    isLoading: query.isLoading,
    sendMessage: mutation.mutate,
  };
};
```

---

## Real-Time Features

### Server-Sent Events (SSE) for Chat Streaming

```typescript
// hooks/useSSE.ts
const useSSE = (url: string) => {
  const [data, setData] = useState([]);

  useEffect(() => {
    const eventSource = new EventSource(url);

    eventSource.addEventListener("status", (e) => {
      setData((prev) => [...prev, JSON.parse(e.data)]);
    });

    eventSource.addEventListener("sources", (e) => {
      // Update UI with sources
    });

    eventSource.addEventListener("response_chunk", (e) => {
      // Stream response text
    });

    eventSource.addEventListener("metadata", (e) => {
      // Update confidence, tokens, latency
    });

    return () => eventSource.close();
  }, [url]);

  return data;
};

// In ChatInterface component
const response = useSSE(`/api/v1/chat/stream?query=${query}`);
```

### WebSocket for Real-Time Notifications

```typescript
// hooks/useWebSocket.ts
const useWebSocket = (url: string) => {
  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    const ws = new WebSocket(url);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "notification") {
        setNotifications((prev) => [...prev, message]);
        // Show toast
      }
    };

    return () => ws.close();
  }, [url]);

  return notifications;
};
```

---

## Authentication Flow

### Login Flow

```typescript
// pages/auth/login.tsx

const LoginPage = () => {
  const handleMicrosoftLogin = () => {
    // Redirect to backend auth endpoint
    window.location.href = `${API_URL}/api/v1/auth/login`;
  };

  return (
    <div className="login-container">
      <button onClick={handleMicrosoftLogin}>
        Sign in with Microsoft
      </button>
    </div>
  );
};
```

### OAuth Callback

```typescript
// pages/auth/callback.tsx

const CallbackPage = () => {
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('code');

    if (code) {
      // Exchange code for JWT
      api.post('/api/v1/auth/callback', { code })
        .then(({ token }) => {
          localStorage.setItem('jwt_token', token);
          router.push('/chat');
        });
    }
  }, []);

  return <div>Logging in...</div>;
};
```

### Protected Routes

```typescript
// components/auth/AuthGuard.tsx

const AuthGuard = ({ children }: { children: React.ReactNode }) => {
  const { user, isLoading } = useAuth();

  if (isLoading) return <LoadingSpinner />;

  if (!user) {
    return <Navigate to="/auth/login" />;
  }

  return children;
};

// Usage in layout or page
<AuthGuard>
  <ChatPage />
</AuthGuard>
```

---

## API Integration

### API Client Factory

```typescript
// lib/api.ts

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Add JWT token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("jwt_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle token expiration
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Refresh token or redirect to login
      localStorage.removeItem("jwt_token");
      window.location.href = "/auth/login";
    }
    return Promise.reject(error);
  },
);

export const api = apiClient;
```

---

## Component Patterns

### Chat Message Component

```typescript
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  confidence?: number;
  createdAt: string;
}

const ChatMessage = ({ message }: { message: Message }) => {
  return (
    <div className={cn(
      "flex gap-3 mb-4",
      message.role === 'user' ? 'justify-end' : 'justify-start'
    )}>
      {message.role === 'assistant' && <Avatar src={botAvatar} />}

      <div className="max-w-lg">
        <p className="text-sm text-gray-600">{message.content}</p>

        {message.sources && (
          <div className="mt-2 flex gap-2">
            {message.sources.map(source => (
              <SourceBadge key={source.id} source={source} />
            ))}
          </div>
        )}

        {message.confidence && (
          <ConfidenceBadge score={message.confidence} />
        )}
      </div>
    </div>
  );
};
```

---

## Testing

### Unit Tests (Vitest)

```typescript
// __tests__/hooks/useAuth.test.ts

describe("useAuth", () => {
  it("should fetch current user", async () => {
    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.isAuthenticated).toBe(true);
    });

    expect(result.current.user.email).toBe("user@company.com");
  });

  it("should handle logout", async () => {
    const { result } = renderHook(() => useAuth());

    await result.current.logout();

    expect(localStorage.getItem("jwt_token")).toBeNull();
  });
});
```

### E2E Tests (Playwright)

```typescript
// tests/chat.spec.ts

test("user can send message and receive response", async ({ page }) => {
  // Login
  await page.goto("/auth/login");
  await page.click('[data-testid="microsoft-login"]');
  // ... Azure AD flow ...

  // Navigate to chat
  await page.goto("/chat");

  // Send message
  await page.fill('[data-testid="input-box"]', "What is the PTO policy?");
  await page.click('[data-testid="send-button"]');

  // Wait for response
  await expect(page.locator('[data-testid="message-list"]')).toContainText(
    /PTO policy/i,
    { timeout: 10000 },
  );

  // Check sources displayed
  await expect(page.locator('[data-testid="sources"]')).toBeVisible();
});
```

---

## Performance Optimization

### Code Splitting

```typescript
// pages/admin/index.tsx - Lazy load admin components

const AdminUsers = dynamic(() => import('@/components/admin/UserTable'), {
  loading: () => <LoadingSpinner />,
  ssr: false  // Don't render on server
});
```

### Image Optimization

```typescript
import Image from 'next/image';

<Image
  src="/logo.png"
  alt="Logo"
  width={200}
  height={100}
  priority={true}  // For above-the-fold images
/>
```

### Query Caching

```typescript
// Only refetch when stale
const useMessages = (conversationId: string) => {
  return useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () => fetchMessages(conversationId),
    staleTime: 1 * 60 * 1000, // 1 minute
    cacheTime: 10 * 60 * 1000, // 10 minutes
  });
};
```

---

## Environment Variables

```bash
# .env.local

NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_AUTH_MODE=dual
NEXT_PUBLIC_WEBSOCKET_URL=ws://localhost:8000/ws
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
