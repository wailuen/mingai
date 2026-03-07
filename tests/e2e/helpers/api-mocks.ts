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
