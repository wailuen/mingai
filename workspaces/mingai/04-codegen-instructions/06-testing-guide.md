# 06 — Testing Guide

**Rules**: No mocking in Tier 2/3. Real infrastructure only. Tests written BEFORE implementation (TDD).

Read `todos/active/05-testing.md` for the full test list (TEST-001 through TEST-074).

---

## 3-Tier Testing Structure

```
tests/
├── unit/           # Tier 1: fast, mocking ALLOWED
├── integration/    # Tier 2: real PostgreSQL + Redis, NO MOCKING
└── e2e/           # Tier 3: real browser + real backend, NO MOCKING
```

### Coverage Requirements

| Code Type                    | Minimum Coverage |
| ---------------------------- | ---------------- |
| General backend              | 80%              |
| Auth / JWT validation        | 100%             |
| GDPR (clear_profile_data)    | 100%             |
| RLS enforcement              | 100%             |
| Financial (HAR transactions) | 100%             |
| Memory note 200-char limit   | 100%             |

---

## Tier 1: Unit Tests

Mocking allowed. Fast (<1s per test). Test isolated functions.

```python
# tests/unit/test_glossary_expander.py
import pytest
from app.modules.glossary.expander import GlossaryExpander

class TestGlossaryExpander:
    """20+ tests covering all edge cases (see todos/active/03-ai-services.md AI-035)."""

    @pytest.mark.asyncio
    async def test_basic_expansion(self, mock_redis_with_terms):
        expander = GlossaryExpander()
        expanded, expansions = await expander.expand("What is AL policy?", "tenant-1")
        assert "Annual Leave" in expanded
        assert len(expansions) == 1

    async def test_stop_word_not_expanded(self, mock_redis_with_terms):
        expander = GlossaryExpander()
        expanded, _ = await expander.expand("Is it available?", "tenant-1")
        assert "it (" not in expanded  # "it" is a stop word

    async def test_short_term_requires_uppercase(self, mock_redis_with_terms):
        expander = GlossaryExpander()
        # "al" (lowercase) should NOT expand
        expanded, _ = await expander.expand("al was late", "tenant-1")
        assert "Annual Leave" not in expanded
        # "AL" (uppercase) SHOULD expand
        expanded, _ = await expander.expand("AL was taken", "tenant-1")
        assert "Annual Leave" in expanded

    async def test_first_occurrence_only(self, mock_redis_with_terms):
        expander = GlossaryExpander()
        expanded, expansions = await expander.expand("AL and AL policy for AL", "tenant-1")
        # Only first "AL" should be expanded
        assert expanded.count("Annual Leave") == 1

    async def test_full_form_longer_than_50_chars_skipped(self, mock_redis):
        # Term with full_form > 50 chars should not be expanded
        ...

    async def test_cjk_uses_fullwidth_parens(self, mock_redis_with_terms):
        expander = GlossaryExpander()
        expanded, _ = await expander.expand("AL政策について", "tenant-1")
        assert "（" in expanded and "）" in expanded

    async def test_deduplication_across_aliases(self, mock_redis_with_terms):
        # If term and alias match the same text, expand only once
        ...

    async def test_max_10_expansions(self, mock_redis_with_many_terms):
        expander = GlossaryExpander()
        _, expansions = await expander.expand("A B C D E F G H I J K", "tenant-1")
        assert len(expansions) <= 10
```

```python
# tests/unit/test_profile_learning.py
import pytest
from app.modules.profile.learning import ProfileLearningService

class TestProfileLearningService:
    """30+ tests (see todos/active/03-ai-services.md AI-001 to AI-010)."""

    async def test_query_count_triggers_extraction_at_threshold(self, mock_redis, mock_db):
        service = ProfileLearningService()
        # Simulate 9 queries (should not trigger)
        for i in range(9):
            await service.on_query_completed("user-1", "tenant-1", "agent-1")
        assert not mock_db.extraction_called

        # 10th query triggers extraction
        await service.on_query_completed("user-1", "tenant-1", "agent-1")
        assert mock_db.extraction_called

    async def test_only_user_queries_sent_to_extraction_llm(self, mock_redis, mock_llm):
        """CRITICAL: only user messages sent to LLM (not full conversation)."""
        service = ProfileLearningService()
        await service._run_profile_extraction("user-1", "tenant-1", "agent-1")
        # Verify LLM was called only with user query content
        call_args = mock_llm.last_call_messages
        assert all(msg["role"] != "assistant" for msg in call_args[1:])

    async def test_redis_key_includes_tenant_prefix(self, redis_client):
        service = ProfileLearningService()
        await service.on_query_completed("user-1", "tenant-abc", "agent-1")
        keys = await redis_client.keys("*")
        assert any(k.startswith("mingai:tenant-abc:") for k in keys)
```

---

## Tier 2: Integration Tests

**NO MOCKING**. Real PostgreSQL and Redis. Use Docker for CI.

```python
# tests/integration/conftest.py
import pytest
import pytest_asyncio
from dataflow import DataFlow
from redis.asyncio import Redis
from dotenv import load_dotenv

load_dotenv()  # MUST load .env before any import

@pytest_asyncio.fixture(scope="session")
async def db():
    """Real PostgreSQL connection. NOT SQLite."""
    database = DataFlow(os.environ["TEST_DATABASE_URL"])
    yield database
    await database.close()

@pytest_asyncio.fixture(scope="session")
async def redis_client():
    """Real Redis connection."""
    client = Redis.from_url(os.environ["TEST_REDIS_URL"])
    yield client
    await client.aclose()

@pytest_asyncio.fixture
async def tenant_a(db):
    """Create real test tenant A."""
    tenant = await db.execute(CreateTenant(
        name="Test Tenant A",
        slug="test-a",
        plan="professional",
        primary_contact_email="admin@test-a.com"
    ))
    yield tenant
    await db.execute(DeleteTenant(id=tenant.id))  # cleanup

@pytest_asyncio.fixture
async def tenant_b(db):
    """Create real test tenant B."""
    tenant = await db.execute(CreateTenant(
        name="Test Tenant B",
        slug="test-b",
        plan="professional",
        primary_contact_email="admin@test-b.com"
    ))
    yield tenant
    await db.execute(DeleteTenant(id=tenant.id))
```

### Security Gate Tests (ALL MUST PASS Before Deployment)

```python
# tests/integration/test_tenant_isolation.py (TEST-001)
class TestTenantIsolation:
    """RLS enforcement — 100% coverage required."""

    async def test_rls_prevents_cross_tenant_read(self, db, tenant_a, tenant_b):
        # Create conversation as tenant A
        with db.set_tenant(str(tenant_a.id)):
            conv = await db.execute(CreateConversation(user_id=..., title="secret"))

        # Attempt to read as tenant B — must get 0 rows
        with db.set_tenant(str(tenant_b.id)):
            rows = await db.execute(
                "SELECT * FROM conversations WHERE id = $1", str(conv.id)
            )
            assert len(rows) == 0  # RLS returns nothing

    async def test_api_returns_404_for_cross_tenant_resource(
        self, tenant_a_client, tenant_b_client
    ):
        resp = tenant_a_client.post("/api/v1/conversations", json={"title": "t"})
        conv_id = resp.json()["id"]
        cross_resp = tenant_b_client.get(f"/api/v1/conversations/{conv_id}")
        assert cross_resp.status_code == 404

    async def test_redis_keys_not_accessible_cross_tenant(
        self, redis_client, tenant_a, tenant_b, tenant_b_client
    ):
        # Plant data in tenant A's Redis namespace
        await redis_client.set(
            f"mingai:{tenant_a.id}:working_memory:user1:agent1",
            '{"topics": ["secret"]}'
        )
        # Tenant B's working memory endpoint must not return tenant A's data
        resp = tenant_b_client.get("/api/v1/me/working-memory")
        assert "secret" not in str(resp.json())


# tests/integration/test_gdpr.py (TEST-002)
class TestGDPRCompliance:
    """100% coverage required."""

    async def test_erasure_clears_all_three_stores(
        self, db, redis_client, tenant_a_client, tenant_a, user_a
    ):
        # Create data in all 3 stores
        # 1. PostgreSQL
        await db.execute(CreateUserProfile(user_id=user_a.id, tenant_id=tenant_a.id, ...))
        await db.execute(CreateMemoryNote(user_id=user_a.id, tenant_id=tenant_a.id, ...))

        # 2. Redis
        await redis_client.set(
            f"mingai:{tenant_a.id}:profile_learning:profile:{user_a.id}", "{}"
        )
        await redis_client.set(
            f"mingai:{tenant_a.id}:working_memory:{user_a.id}:agent1", "{}"  # aihub2 bug fix
        )

        # Trigger erasure
        resp = tenant_a_client.delete("/api/v1/me/profile/data")
        assert resp.status_code == 200

        # Verify PostgreSQL cleared
        profiles = await db.execute("SELECT * FROM user_profiles WHERE user_id = $1", user_a.id)
        assert len(profiles) == 0
        notes = await db.execute("SELECT * FROM memory_notes WHERE user_id = $1", user_a.id)
        assert len(notes) == 0

        # Verify Redis cleared (INCLUDING working memory — aihub2 bug fix)
        assert await redis_client.get(
            f"mingai:{tenant_a.id}:profile_learning:profile:{user_a.id}"
        ) is None
        wm_keys = [k async for k in redis_client.scan_iter(
            f"mingai:{tenant_a.id}:working_memory:{user_a.id}:*"
        )]
        assert len(wm_keys) == 0  # CRITICAL: must be 0


# tests/integration/test_memory_notes.py (TEST-003)
class TestMemoryNoteLimits:
    """100% coverage required."""

    async def test_200_char_limit_enforced_at_api(self, tenant_a_client):
        resp = tenant_a_client.post("/api/v1/me/memory", json={"content": "x" * 201})
        assert resp.status_code == 422

    async def test_200_chars_accepted(self, tenant_a_client):
        resp = tenant_a_client.post("/api/v1/me/memory", json={"content": "x" * 200})
        assert resp.status_code == 201


# tests/integration/test_cors.py (TEST-004)
class TestCORSConfiguration:
    """Day-1 security gate."""

    async def test_wildcard_origin_rejected(self, test_client):
        resp = test_client.get(
            "/api/v1/auth/current",
            headers={"Origin": "http://evil.com"}
        )
        # Must NOT include ACAO: * header
        assert resp.headers.get("access-control-allow-origin") != "*"

    async def test_allowed_origin_accepted(self, test_client):
        resp = test_client.get(
            "/api/v1/auth/current",
            headers={"Origin": os.environ["FRONTEND_URL"]}
        )
        assert resp.headers.get("access-control-allow-origin") == os.environ["FRONTEND_URL"]


# tests/integration/test_rate_limiting.py (TEST-005)
class TestRateLimiting:
    async def test_chat_rate_limit_429(self, tenant_a_client):
        """30 requests/minute limit on chat endpoint."""
        for _ in range(30):
            tenant_a_client.post("/api/v1/chat/stream", json={"query": "test", "agent_id": "a"})
        resp = tenant_a_client.post("/api/v1/chat/stream", json={"query": "test", "agent_id": "a"})
        assert resp.status_code == 429

    async def test_auth_brute_force_protection(self, test_client):
        """10 attempts/minute on login endpoint."""
        for _ in range(10):
            test_client.post("/api/v1/auth/local/login", json={"email": "x", "password": "x"})
        resp = test_client.post("/api/v1/auth/local/login", json={"email": "x", "password": "x"})
        assert resp.status_code == 429
```

---

## Tier 3: E2E Tests (Playwright)

**NO MOCKING**. Real browser + real backend.

```typescript
// tests/e2e/chat.spec.ts (TEST-041)
import { test, expect } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test.describe("End User Chat", () => {
  test("empty state → active state on first message", async ({ page }) => {
    await loginAs(page, "end_user");
    await page.goto("/chat");

    // Empty state: centered input visible
    await expect(page.locator("[data-testid=chat-empty-state]")).toBeVisible();

    // Send message
    await page.fill(
      "[data-testid=chat-input]",
      "What is the annual leave policy?",
    );
    await page.click("[data-testid=send-button]");

    // Active state: bottom-fixed input, response visible
    await expect(page.locator("[data-testid=chat-active-state]")).toBeVisible();
    await expect(page.locator("[data-testid=message-list]")).toBeVisible();
  });

  test("retrieval confidence labeled correctly", async ({ page }) => {
    await loginAs(page, "end_user");
    await page.goto("/chat");
    await page.fill("[data-testid=chat-input]", "What is the HR policy?");
    await page.click("[data-testid=send-button]");

    // Wait for response
    await page.waitForSelector("[data-testid=retrieval-confidence]");
    const label = await page.textContent(
      "[data-testid=retrieval-confidence-label]",
    );
    // Must be "retrieval confidence" — NOT "AI confidence" or "answer quality"
    expect(label?.toLowerCase()).toContain("retrieval confidence");
    expect(label?.toLowerCase()).not.toContain("ai confidence");
    expect(label?.toLowerCase()).not.toContain("answer quality");
  });

  test("glossary expansion indicator shown when terms expanded", async ({
    page,
  }) => {
    // Requires glossary terms to exist in test tenant
    await loginAs(page, "end_user");
    await page.goto("/chat");
    await page.fill("[data-testid=chat-input]", "What is the AL policy?");
    await page.click("[data-testid=send-button]");

    await page.waitForSelector("[data-testid=glossary-expansion-indicator]");
    await expect(
      page.locator("[data-testid=glossary-expansion-indicator]"),
    ).toBeVisible();
  });

  test("thumbs feedback submits successfully", async ({ page }) => {
    await loginAs(page, "end_user");
    await page.goto("/chat");
    await page.fill("[data-testid=chat-input]", "Test query");
    await page.click("[data-testid=send-button]");
    await page.waitForSelector("[data-testid=feedback-thumbsup]");
    await page.click("[data-testid=feedback-thumbsup]");
    // Verify button state changes (not just API call)
    await expect(page.locator("[data-testid=feedback-thumbsup]")).toHaveClass(
      /active/,
    );
  });
});

// tests/e2e/cross-tenant-isolation.spec.ts (TEST-045 — CRITICAL)
test.describe("Cross-Tenant Isolation", () => {
  test("tenant A data not visible to tenant B user", async ({ browser }) => {
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();
    const pageA = await contextA.newPage();
    const pageB = await contextB.newPage();

    await loginAs(pageA, "tenant_a_user");
    await loginAs(pageB, "tenant_b_user");

    // Tenant A creates a conversation
    await pageA.goto("/chat");
    await pageA.fill("[data-testid=chat-input]", "Secret A conversation");
    await pageA.click("[data-testid=send-button]");
    const convUrl = pageA.url();
    const convId = convUrl.split("/").pop();

    // Tenant B tries to navigate directly to conversation URL
    await pageB.goto(`/chat/${convId}`);
    // Must redirect to /chat (empty state) — not show conversation
    await expect(pageB).toHaveURL(/\/chat$/);
  });
});

// tests/e2e/privacy-settings.spec.ts (TEST-052)
test.describe("Privacy Settings", () => {
  test("privacy disclosure dialog shown on first profile use", async ({
    page,
  }) => {
    await loginAs(page, "new_user");
    await page.goto("/chat");
    // After first response, disclosure dialog appears
    await page.fill("[data-testid=chat-input]", "Test query");
    await page.click("[data-testid=send-button]");
    await page.waitForSelector("[data-testid=privacy-disclosure-dialog]");
    // Dialog is transparency (not consent gate) — dismiss button visible
    await expect(page.locator("[data-testid=privacy-dismiss]")).toBeVisible();
    // No "I agree" or "Consent" button
    await expect(page.locator("text=I agree")).not.toBeVisible();
    await expect(page.locator("text=Consent")).not.toBeVisible();
  });

  test("memory note cleared on delete", async ({ page }) => {
    await loginAs(page, "end_user");
    await page.goto("/settings/privacy");
    // Send "remember that" command first
    await page.goto("/chat");
    await page.fill(
      "[data-testid=chat-input]",
      "Remember that I prefer concise answers",
    );
    await page.click("[data-testid=send-button]");
    await page.waitForSelector("[data-testid=memory-saved-toast]");
    // Navigate to privacy, verify note appears, delete it
    await page.goto("/settings/privacy");
    await expect(
      page.locator("[data-testid=memory-note]").first(),
    ).toBeVisible();
    await page.click("[data-testid=delete-note-button]");
    await page.waitForSelector("[data-testid=memory-empty-state]");
  });
});
```

---

## E2E Test Helpers

```typescript
// tests/e2e/helpers/auth.ts
import { Page } from "@playwright/test";

type Role =
  | "platform_admin"
  | "tenant_admin"
  | "end_user"
  | "new_user"
  | "tenant_a_user"
  | "tenant_b_user";

const USERS: Record<Role, { email: string; password: string }> = {
  platform_admin: {
    email: process.env.E2E_PLATFORM_ADMIN_EMAIL!,
    password: process.env.E2E_PLATFORM_ADMIN_PASS!,
  },
  tenant_admin: {
    email: process.env.E2E_TENANT_ADMIN_EMAIL!,
    password: process.env.E2E_TENANT_ADMIN_PASS!,
  },
  end_user: {
    email: process.env.E2E_END_USER_EMAIL!,
    password: process.env.E2E_END_USER_PASS!,
  },
  // etc.
};

export async function loginAs(page: Page, role: Role) {
  // Never hardcode credentials — read from .env
  const { email, password } = USERS[role];
  await page.goto("/login");
  await page.fill("[name=email]", email);
  await page.fill("[name=password]", password);
  await page.click("[type=submit]");
  await page.waitForURL(/\/(chat|admin)/);
}
```

---

## Migration Tests (TEST-073)

```python
# tests/integration/test_migrations.py

def test_migration_up_down_up(test_db_url):
    """Every migration must be reversible."""
    import subprocess
    for migration in get_migration_files():
        # Apply
        subprocess.run(["alembic", "upgrade", migration], check=True)
        # Rollback
        subprocess.run(["alembic", "downgrade", "-1"], check=True)
        # Re-apply
        subprocess.run(["alembic", "upgrade", migration], check=True)

def test_rls_canary_after_migration(db):
    """After migration, RLS must be active on all tables."""
    tables_with_tenant_id = [
        "users", "conversations", "messages", "user_profiles",
        "memory_notes", "profile_learning_events", "tenant_teams",
        "team_memberships", "glossary_terms",
    ]
    for table in tables_with_tenant_id:
        result = db.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = $1", table
        ).fetchone()
        assert result["relrowsecurity"] is True, f"RLS not enabled on {table}"
```

---

## Load Testing (TEST-074)

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class ChatUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        resp = self.client.post("/api/v1/auth/local/login", json={
            "email": os.environ["E2E_END_USER_EMAIL"],
            "password": os.environ["E2E_END_USER_PASS"]
        })
        self.token = resp.json()["access_token"]

    @task(3)
    def chat_query(self):
        self.client.post(
            "/api/v1/chat/stream",
            json={"query": "What is the annual leave policy?", "agent_id": "default"},
            headers={"Authorization": f"Bearer {self.token}"},
            stream=True
        )

    @task(1)
    def view_conversations(self):
        self.client.get(
            "/api/v1/conversations",
            headers={"Authorization": f"Bearer {self.token}"}
        )

# Run: locust -f tests/load/locustfile.py --host=http://localhost:8022
# Target: 100 concurrent users, p95 latency < 3s for chat
```

---

## CI Configuration

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: pytest tests/unit/ -v --cov=app --cov-report=xml
      - run: coverage report --fail-under=80

  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: mingai_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: alembic upgrade head
        env:
          DATABASE_URL: postgresql+asyncpg://test:test@localhost/mingai_test
      - run: pytest tests/integration/ -v
        env:
          TEST_DATABASE_URL: postgresql+asyncpg://test:test@localhost/mingai_test
          TEST_REDIS_URL: redis://localhost:6379/1

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npx playwright install --with-deps
      - run: npx playwright test
        env:
          PLAYWRIGHT_BASE_URL: http://localhost:3022
```

---

## 7 Security Gates (All Must Pass Before Deploy)

Run in this order:

```bash
# Gate 1: RLS canary
pytest tests/integration/test_migrations.py::test_rls_canary_after_migration -v

# Gate 2: Cross-tenant isolation
pytest tests/integration/test_tenant_isolation.py -v

# Gate 3: GDPR erasure (including working memory)
pytest tests/integration/test_gdpr.py -v

# Gate 4: CORS wildcard rejection
pytest tests/integration/test_cors.py -v

# Gate 5: Rate limiting
pytest tests/integration/test_rate_limiting.py -v

# Gate 6: Memory note 200-char limit
pytest tests/integration/test_memory_notes.py::TestMemoryNoteLimits -v

# Gate 7: Screenshot blur (E2E)
npx playwright test tests/e2e/issue-reporting.spec.ts --grep "screenshot blur"
```

All 7 must show PASS. Any failure = block deployment.
