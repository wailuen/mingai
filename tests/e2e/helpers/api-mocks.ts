import { type Page } from "@playwright/test";

/**
 * Mock API responses by intercepting fetch requests via Playwright route.
 * This allows E2E tests to run without a live backend.
 */

/** Intercept the SSE chat endpoint and return a scripted response. */
export async function mockChatStream(
  page: Page,
  options: {
    responseText?: string;
    sources?: Array<{
      id: string;
      title: string;
      url: string;
      score: number;
      excerpt: string;
    }>;
    conversationId?: string;
    messageId?: string;
    mode?: string;
  } = {},
): Promise<void> {
  const {
    responseText = "This is a test response from the AI assistant.",
    sources = [],
    conversationId = "conv-test-001",
    messageId = "msg-test-001",
    mode = "auto",
  } = options;

  await page.route("**/api/v1/chat/stream**", async (route) => {
    const events: string[] = [];

    events.push(
      `event: status\ndata: ${JSON.stringify({ message: "Searching documents..." })}\n\n`,
    );

    if (sources.length > 0) {
      events.push(`event: sources\ndata: ${JSON.stringify({ sources })}\n\n`);
    }

    events.push(
      `event: response_chunk\ndata: ${JSON.stringify({ text: responseText })}\n\n`,
    );

    events.push(
      `event: metadata\ndata: ${JSON.stringify({
        retrieval_confidence: 0.85,
        glossary_expansions: [],
        profile_context_used: false,
        layers_active: [],
      })}\n\n`,
    );

    events.push(
      `event: done\ndata: ${JSON.stringify({
        message_id: messageId,
        conversation_id: conversationId,
      })}\n\n`,
    );

    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      body: events.join(""),
    });
  });
}

/** Intercept the chat feedback endpoint. */
export async function mockChatFeedback(page: Page): Promise<void> {
  await page.route("**/api/v1/chat/feedback", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "fb-001", rating: "up" }),
    });
  });
}

/** Mock the glossary terms list API. */
export async function mockGlossaryTerms(page: Page): Promise<void> {
  await page.route("**/api/v1/glossary/terms**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "term-001",
            term: "ARR",
            full_form: "Annual Recurring Revenue",
            definition:
              "The annualized value of recurring subscription revenue.",
            aliases: ["annual recurring revenue"],
            is_active: true,
          },
          {
            id: "term-002",
            term: "CSAT",
            full_form: "Customer Satisfaction Score",
            definition:
              "A metric used to measure customer satisfaction with a product or service.",
            aliases: [],
            is_active: true,
          },
          {
            id: "term-003",
            term: "MRR",
            full_form: "Monthly Recurring Revenue",
            definition:
              "The normalized monthly recurring revenue from subscriptions.",
            aliases: ["monthly recurring revenue"],
            is_active: false,
          },
        ],
        total: 3,
        page: 1,
        page_size: 50,
      }),
    });
  });
}

/** Mock the glossary export CSV endpoint. */
export async function mockGlossaryExport(page: Page): Promise<void> {
  await page.route("**/api/v1/glossary/export**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": 'attachment; filename="glossary.csv"',
      },
      body: "term,full_form,definition,status\nARR,Annual Recurring Revenue,The annualized value,active\n",
    });
  });
}

/** Mock the miss signals API. */
export async function mockMissSignals(page: Page): Promise<void> {
  await page.route("**/api/v1/glossary/miss-signals**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            term: "NPS",
            occurrence_count: 14,
            last_seen: "2026-03-07T10:30:00Z",
          },
          {
            term: "CAC",
            occurrence_count: 8,
            last_seen: "2026-03-06T14:20:00Z",
          },
        ],
      }),
    });
  });
}

/** Mock the SSO config API -- not configured state. */
export async function mockSSONotConfigured(page: Page): Promise<void> {
  await page.route("**/api/v1/sso/config**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "not_configured", provider: null }),
    });
  });
}

/** Mock the SSO config API -- configured SAML state. */
export async function mockSSOConfigured(page: Page): Promise<void> {
  await page.route("**/api/v1/sso/config**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "configured",
        provider: "saml",
        saml: {
          entity_id: "https://sso.mingai.test/saml",
          acs_url: "https://app.mingai.test/api/auth/saml/callback",
          metadata_url: "https://sso.mingai.test/saml/metadata",
        },
      }),
    });
  });
}

/** Mock issue reporting config API. */
export async function mockIssueReportingConfig(page: Page): Promise<void> {
  await page.route("**/api/v1/settings/issue-reporting**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          notify_email: "admin@company.com",
          auto_escalate_p0: true,
          auto_escalate_p1: false,
          escalation_threshold_hours: 4,
          slack_webhook_url: "",
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    }
  });
}

/** Mock the integrations (knowledge base / sync health) API. */
export async function mockIntegrations(page: Page): Promise<void> {
  await page.route("**/api/v1/integrations**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "int-001",
          type: "sharepoint",
          name: "Corporate SharePoint",
          status: "healthy",
          doc_count: 1420,
          last_sync: "2026-03-08T01:00:00Z",
          freshness_hours: 2,
        },
        {
          id: "int-002",
          type: "sharepoint",
          name: "HR SharePoint",
          status: "warning",
          doc_count: 661,
          last_sync: "2026-03-07T18:00:00Z",
          freshness_hours: 9,
        },
      ]),
    });
  });
}

/** Mock the conversations list API. */
export async function mockConversationsList(page: Page): Promise<void> {
  await page.route("**/api/v1/conversations**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        total: 0,
        page: 1,
        limit: 20,
        total_pages: 0,
      }),
    });
  });
}

// ---------------------------------------------------------------------------
// TEST-020: Issue Reporting mocks
// ---------------------------------------------------------------------------

/** Mock the issue submit endpoint (POST). */
export async function mockIssueSubmit(page: Page): Promise<void> {
  await page.route("**/api/v1/issues**", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "issue-test-001",
          severity: "P1",
          status: "new",
          title: "Test issue",
          description: "Issue description",
          created_at: "2026-03-09T10:00:00Z",
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "issue-test-001",
              severity: "P1",
              status: "new",
              title: "Incorrect answer about leave policy",
              description: "The AI gave wrong information about the annual leave entitlement.",
              reporter_email: "testuser@mingai.test",
              created_at: "2026-03-09T10:00:00Z",
              tenant_id: "tenant-001",
            },
            {
              id: "issue-test-002",
              severity: "P0",
              status: "open",
              title: "Salary data exposed in response",
              description: "The AI leaked another employee salary in the response.",
              reporter_email: "user2@mingai.test",
              created_at: "2026-03-08T09:00:00Z",
              tenant_id: "tenant-001",
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        }),
      });
    }
  });
}

/** Mock the tenant issue queue list for tenant admin. */
export async function mockTenantIssueQueue(page: Page): Promise<void> {
  await page.route("**/api/v1/tenant/issues**", async (route) => {
    const method = route.request().method();
    if (method === "PATCH") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "issue-test-001",
              severity: "P1",
              status: "new",
              title: "Incorrect answer about leave policy",
              description: "The AI gave wrong information about the annual leave entitlement.",
              reporter_email: "testuser@mingai.test",
              created_at: "2026-03-09T10:00:00Z",
            },
            {
              id: "issue-test-002",
              severity: "P0",
              status: "open",
              title: "Salary data exposed in response",
              description: "The AI leaked another employee salary in the response.",
              reporter_email: "user2@mingai.test",
              created_at: "2026-03-08T09:00:00Z",
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        }),
      });
    }
  });
}

// ---------------------------------------------------------------------------
// TEST-025: Platform Admin mocks
// ---------------------------------------------------------------------------

/** Mock platform dashboard KPI + tenant health data. */
export async function mockPlatformDashboard(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/dashboard**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        active_users: 1247,
        documents_indexed: 42680,
        queries_today: 3842,
        satisfaction: 87.2,
        tenants: [
          {
            id: "tenant-001",
            name: "Acme Corp",
            plan: "enterprise",
            status: "active",
            health_score: 92,
            users: 420,
            primary_contact_email: "admin@acme.com",
            created_at: "2025-06-15T00:00:00Z",
          },
          {
            id: "tenant-002",
            name: "Beta Inc",
            plan: "professional",
            status: "active",
            health_score: 67,
            users: 85,
            primary_contact_email: "admin@beta.com",
            created_at: "2025-09-01T00:00:00Z",
          },
          {
            id: "tenant-003",
            name: "Gamma LLC",
            plan: "starter",
            status: "suspended",
            health_score: 34,
            users: 12,
            primary_contact_email: "admin@gamma.com",
            created_at: "2025-11-20T00:00:00Z",
          },
        ],
      }),
    });
  });
}

/** Mock platform tenant list. */
export async function mockTenantList(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/tenants", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "tenant-001",
              name: "Acme Corp",
              slug: "acme-corp",
              plan: "enterprise",
              status: "active",
              primary_contact_email: "admin@acme.com",
              created_at: "2025-06-15T00:00:00Z",
            },
            {
              id: "tenant-002",
              name: "Beta Inc",
              slug: "beta-inc",
              plan: "professional",
              status: "active",
              primary_contact_email: "admin@beta.com",
              created_at: "2025-09-01T00:00:00Z",
            },
            {
              id: "tenant-003",
              name: "Gamma LLC",
              slug: "gamma-llc",
              plan: "starter",
              status: "suspended",
              primary_contact_email: "admin@gamma.com",
              created_at: "2025-11-20T00:00:00Z",
            },
          ],
          total: 3,
          page: 1,
          page_size: 20,
        }),
      });
    } else {
      // POST for provisioning
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "tenant-new-001",
          name: "Test Corp",
          slug: "test-corp",
          plan: "professional",
          status: "active",
          primary_contact_email: "admin@test.com",
          created_at: "2026-03-09T00:00:00Z",
        }),
      });
    }
  });
}

/** Mock platform tenant detail (by id). */
export async function mockTenantDetail(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/tenants/*", async (route) => {
    const method = route.request().method();
    if (method === "PATCH") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "tenant-001",
          name: "Acme Corp",
          slug: "acme-corp",
          plan: "enterprise",
          status: "active",
          primary_contact_email: "admin@acme.com",
          created_at: "2025-06-15T00:00:00Z",
          health_score: 92,
          users: 420,
        }),
      });
    }
  });
}

/** Mock LLM profiles list. */
export async function mockLLMProfiles(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/llm-profiles**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "prof-001",
            name: "GPT-4o Production",
            provider: "azure",
            model: "gpt-4o",
            deployment_name: "agentic-worker",
            endpoint: "https://eastus2.api.cognitive.microsoft.com/",
            slot: "primary",
            status: "active",
            created_at: "2025-12-01T00:00:00Z",
          },
          {
            id: "prof-002",
            name: "GPT-4o Mini Router",
            provider: "azure",
            model: "gpt-4o-mini",
            deployment_name: "agentic-router",
            endpoint: "https://eastus2.api.cognitive.microsoft.com/",
            slot: "intent",
            status: "active",
            created_at: "2025-12-01T00:00:00Z",
          },
        ],
        total: 2,
        page: 1,
        page_size: 20,
      }),
    });
  });
}

/** Mock cost analytics summary. */
export async function mockCostAnalytics(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/analytics/cost**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total_llm_cost: 12450.0,
        total_infra_cost: 3200.0,
        total_revenue: 28500.0,
        gross_margin: 82.3,
        trend: [
          { date: "2026-02-07", cost: 380, revenue: 950 },
          { date: "2026-02-14", cost: 420, revenue: 960 },
          { date: "2026-02-21", cost: 395, revenue: 980 },
          { date: "2026-02-28", cost: 410, revenue: 970 },
          { date: "2026-03-07", cost: 450, revenue: 1020 },
        ],
        tenants: [
          {
            tenant_id: "tenant-001",
            name: "Acme Corp",
            llm_cost: 8200,
            infra_cost: 1800,
            revenue: 18000,
            queries: 28400,
          },
          {
            tenant_id: "tenant-002",
            name: "Beta Inc",
            llm_cost: 4250,
            infra_cost: 1400,
            revenue: 10500,
            queries: 14200,
          },
        ],
      }),
    });
  });
}

/** Mock the health breakdown endpoint for tenant detail. */
export async function mockHealthBreakdown(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/tenants/*/health**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        overall: 92,
        components: {
          response_quality: 95,
          sync_health: 88,
          uptime: 99,
          satisfaction: 87,
        },
      }),
    });
  });
}

/** Mock the quota usage endpoint for tenant detail. */
export async function mockQuotaUsage(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/tenants/*/quota**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        queries: { used: 28400, limit: 50000 },
        storage_gb: { used: 12.4, limit: 50.0 },
        users: { used: 420, limit: 1000 },
      }),
    });
  });
}

// ---------------------------------------------------------------------------
// TEST-049: Agent Registry mocks
// ---------------------------------------------------------------------------

/** Mock the public agent registry list. */
export async function mockPublicAgents(page: Page): Promise<void> {
  await page.route("**/api/v1/registry/agents**", async (route) => {
    const url = route.request().url();
    if (url.includes("/request")) {
      // POST request access
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "requested" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "agent-001",
          name: "Finance Assistant",
          description: "Answers questions about invoices, budgets, and financial reports.",
          category: "Finance",
          publisher: "mingai",
          satisfaction_rate: 94,
          install_count: 1280,
          capabilities: ["Invoice lookup", "Budget analysis", "Report generation"],
          is_installed: false,
        },
        {
          id: "agent-002",
          name: "HR Helper",
          description: "Handles leave policies, benefits, and onboarding queries.",
          category: "HR",
          publisher: "mingai",
          satisfaction_rate: 91,
          install_count: 2150,
          capabilities: ["Leave policy", "Benefits", "Onboarding"],
          is_installed: true,
        },
        {
          id: "agent-003",
          name: "Legal Advisor",
          description: "Reviews contracts and answers compliance questions.",
          category: "Legal",
          publisher: "mingai",
          satisfaction_rate: 88,
          install_count: 640,
          capabilities: ["Contract review", "Compliance", "NDA analysis"],
          is_installed: false,
        },
      ]),
    });
  });
}

// ---------------------------------------------------------------------------
// TEST-059: Profile & Memory mocks
// ---------------------------------------------------------------------------

/** Mock the user profile endpoint. */
export async function mockUserProfile(page: Page): Promise<void> {
  await page.route("**/api/v1/me/profile**", async (route) => {
    const url = route.request().url();

    if (url.includes("/export")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "test-user-001",
          email: "testuser@mingai.test",
          display_name: "Test User",
          department: "Engineering",
          role: "Software Engineer",
          org_context_enabled: true,
          share_manager_info: false,
          memory_notes: [
            { id: "note-001", content: "Prefers detailed technical explanations", source: "user-directed" },
          ],
          created_at: "2025-08-01T00:00:00Z",
        }),
      });
      return;
    }

    if (url.includes("/privacy")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }

    if (url.includes("/data")) {
      // DELETE /api/v1/me/profile/data
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "test-user-001",
        email: "testuser@mingai.test",
        display_name: "Test User",
        department: "Engineering",
        role: "Software Engineer",
        org_context_enabled: true,
        share_manager_info: false,
      }),
    });
  });
}

/** Mock the memory notes CRUD endpoints. */
export async function mockMemoryNotes(page: Page): Promise<void> {
  await page.route("**/api/v1/me/memory**", async (route) => {
    const method = route.request().method();
    const url = route.request().url();

    if (method === "DELETE") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }

    if (method === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "note-new-001",
          content: "New test note",
          source: "user-directed",
          agent_id: null,
          created_at: "2026-03-09T12:00:00Z",
        }),
      });
      return;
    }

    // GET - list notes (check if specific note ID)
    if (url.match(/\/memory\/[^/]+$/)) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "note-001",
          content: "Prefers detailed technical explanations",
          source: "user-directed",
          agent_id: null,
          created_at: "2026-03-01T10:00:00Z",
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "note-001",
          content: "Prefers detailed technical explanations",
          source: "user-directed",
          agent_id: null,
          created_at: "2026-03-01T10:00:00Z",
        },
        {
          id: "note-002",
          content: "Works on Project Alpha team",
          source: "auto-extracted",
          agent_id: "agent-001",
          created_at: "2026-03-05T14:30:00Z",
        },
        {
          id: "note-003",
          content: "Reports to Jane Smith",
          source: "auto-extracted",
          agent_id: null,
          created_at: "2026-03-07T09:15:00Z",
        },
      ]),
    });
  });
}

// ---------------------------------------------------------------------------
// TEST-040: KB Access Control mocks
// ---------------------------------------------------------------------------

/** Mock the KB list endpoint for tenant admin. */
export async function mockKBList(page: Page): Promise<void> {
  await page.route("**/api/v1/admin/kb**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    // PATCH /admin/kb/:id — update access mode
    if (method === "PATCH" && url.match(/\/admin\/kb\/[^/?]+$/)) {
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: url.split("/").pop(),
          access_mode: body?.access_mode ?? "workspace",
          success: true,
        }),
      });
      return;
    }

    // GET /admin/kb/:id — single KB detail
    if (method === "GET" && url.match(/\/admin\/kb\/[^/?]+$/)) {
      const kbId = url.split("/").pop();
      const kb = {
        id: kbId,
        name: kbId === "kb-001" ? "Corporate Policies" : "Agent-Only KB",
        source_type: "sharepoint",
        doc_count: kbId === "kb-001" ? 1420 : 85,
        access_mode: kbId === "kb-003" ? "agent_only" : "workspace",
        status: "healthy",
        last_sync: "2026-03-08T01:00:00Z",
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(kb),
      });
      return;
    }

    // GET /admin/kb — list
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "kb-001",
            name: "Corporate Policies",
            source_type: "sharepoint",
            doc_count: 1420,
            access_mode: "workspace",
            status: "healthy",
            last_sync: "2026-03-08T01:00:00Z",
          },
          {
            id: "kb-002",
            name: "HR Documents",
            source_type: "sharepoint",
            doc_count: 661,
            access_mode: "role",
            status: "warning",
            last_sync: "2026-03-07T18:00:00Z",
          },
          {
            id: "kb-003",
            name: "Agent Training Data",
            source_type: "upload",
            doc_count: 85,
            access_mode: "agent_only",
            status: "healthy",
            last_sync: "2026-03-09T06:00:00Z",
          },
          {
            id: "kb-004",
            name: "Finance Reports",
            source_type: "google_drive",
            doc_count: 310,
            access_mode: "user",
            status: "healthy",
            last_sync: "2026-03-08T12:00:00Z",
          },
        ],
        total: 4,
        page: 1,
        page_size: 20,
      }),
    });
  });
}

/** Mock the user-facing KB list (end-user visible KBs — excludes agent_only). */
export async function mockUserKBList(page: Page): Promise<void> {
  await page.route("**/api/v1/kb**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "kb-001",
            name: "Corporate Policies",
            source_type: "sharepoint",
            doc_count: 1420,
          },
          {
            id: "kb-002",
            name: "HR Documents",
            source_type: "sharepoint",
            doc_count: 661,
          },
          {
            id: "kb-004",
            name: "Finance Reports",
            source_type: "google_drive",
            doc_count: 310,
          },
        ],
        total: 3,
        page: 1,
        page_size: 20,
      }),
    });
  });
}

/** Mock the agent config KB list (includes agent_only KBs). */
export async function mockAgentConfigKBList(page: Page): Promise<void> {
  await page.route("**/api/v1/admin/agents/*/kb**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "kb-001",
            name: "Corporate Policies",
            access_mode: "workspace",
          },
          {
            id: "kb-003",
            name: "Agent Training Data",
            access_mode: "agent_only",
          },
        ],
        total: 2,
        page: 1,
        page_size: 20,
      }),
    });
  });
}

// ---------------------------------------------------------------------------
// TEST-066: Teams Collaboration mocks
// ---------------------------------------------------------------------------

/** Mock the teams list endpoint for tenant admin. */
export async function mockTeamsList(page: Page): Promise<void> {
  await page.route("**/api/v1/admin/teams**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    // POST /admin/teams — create team
    if (method === "POST" && !url.includes("/members") && !url.includes("/audit")) {
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "team-new-001",
          name: body?.name ?? "New Team",
          type: body?.type ?? "project",
          member_count: 0,
          created_at: "2026-03-09T10:00:00Z",
        }),
      });
      return;
    }

    // GET /admin/teams/:id/audit — audit log
    if (method === "GET" && url.includes("/audit")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "audit-001",
              action: "member_added",
              actor_email: "admin@mingai.test",
              target_email: "alice@mingai.test",
              timestamp: "2026-03-08T14:00:00Z",
            },
            {
              id: "audit-002",
              action: "member_removed",
              actor_email: "admin@mingai.test",
              target_email: "bob@mingai.test",
              timestamp: "2026-03-07T09:30:00Z",
            },
            {
              id: "audit-003",
              action: "team_created",
              actor_email: "admin@mingai.test",
              target_email: null,
              timestamp: "2026-03-01T10:00:00Z",
            },
          ],
          total: 3,
          page: 1,
          page_size: 20,
        }),
      });
      return;
    }

    // POST /admin/teams/:id/members/bulk — CSV upload
    if (method === "POST" && url.includes("/members/bulk")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          added: 3,
          skipped: 1,
          errors: [],
        }),
      });
      return;
    }

    // POST /admin/teams/:id/members — add member
    if (method === "POST" && url.includes("/members")) {
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "member-new-001",
          email: body?.email ?? "newmember@mingai.test",
          name: body?.name ?? "New Member",
          role: body?.role ?? "member",
          added_at: "2026-03-09T12:00:00Z",
        }),
      });
      return;
    }

    // DELETE /admin/teams/:id/members/:memberId — remove member
    if (method === "DELETE" && url.includes("/members/")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }

    // GET /admin/teams/:id — single team detail
    if (method === "GET" && url.match(/\/admin\/teams\/[^/?]+$/) && !url.includes("/audit")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "team-001",
          name: "Engineering",
          type: "department",
          member_count: 24,
          created_at: "2025-11-01T00:00:00Z",
          members: [
            {
              id: "member-001",
              email: "alice@mingai.test",
              name: "Alice Chen",
              role: "lead",
              added_at: "2025-11-01T00:00:00Z",
            },
            {
              id: "member-002",
              email: "bob@mingai.test",
              name: "Bob Smith",
              role: "member",
              added_at: "2025-11-05T00:00:00Z",
            },
            {
              id: "member-003",
              email: "carol@mingai.test",
              name: "Carol Davis",
              role: "member",
              added_at: "2025-12-10T00:00:00Z",
            },
          ],
        }),
      });
      return;
    }

    // GET /admin/teams — list
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "team-001",
            name: "Engineering",
            type: "department",
            member_count: 24,
            created_at: "2025-11-01T00:00:00Z",
          },
          {
            id: "team-002",
            name: "Project Alpha",
            type: "project",
            member_count: 8,
            created_at: "2026-01-15T00:00:00Z",
          },
          {
            id: "team-003",
            name: "Finance",
            type: "department",
            member_count: 12,
            created_at: "2025-09-20T00:00:00Z",
          },
        ],
        total: 3,
        page: 1,
        page_size: 20,
      }),
    });
  });
}

/** Mock the platform issue queue for platform admin. */
export async function mockPlatformIssueQueue(page: Page): Promise<void> {
  await page.route("**/api/v1/platform/issues**", async (route) => {
    const method = route.request().method();
    if (method === "PATCH") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "pissue-001",
              severity: "P0",
              status: "open",
              title: "Data leak in tenant-002",
              description: "PII exposed in AI response.",
              tenant_id: "tenant-002",
              tenant_name: "Beta Inc",
              reporter_email: "user@beta.com",
              created_at: "2026-03-09T08:00:00Z",
            },
            {
              id: "pissue-002",
              severity: "P2",
              status: "in_progress",
              title: "Slow response times for Acme Corp",
              description: "Average latency > 5s for the last hour.",
              tenant_id: "tenant-001",
              tenant_name: "Acme Corp",
              reporter_email: "admin@acme.com",
              created_at: "2026-03-08T16:30:00Z",
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        }),
      });
    }
  });
}
