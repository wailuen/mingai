"""v062 — Pitchbook Skills: Private Markets Intelligence skill library

Revision ID: 062
Revises: 061
Create Date: 2026-03-23

Data migration (no schema changes). Seeds 8 platform skills for the Pitchbook
MCP integration, covering the core private-markets workflows used by PE/VC/M&A
professionals:

  1. Company Due Diligence Brief        — enterprise  — tool_composing
  2. Investor Targeting                 — professional — tool_composing
  3. Deal Comparable Analysis           — enterprise  — tool_composing
  4. Founder & Executive Profile        — professional — tool_composing
  5. Fund Research & Benchmarking       — enterprise  — tool_composing
  6. LP Intelligence Brief              — enterprise  — tool_composing
  7. Portfolio Company Monitor          — professional — tool_composing
  8. Exit Readiness Assessment          — enterprise  — tool_composing

Design decisions:
- Skills are business-task level, not tool-wrapping level.
- All use execution_pattern='tool_composing': the agent calls specific Pitchbook
  tools and synthesises the results into a structured output.
- tool_dependencies JSONB lists the tool names. skill_tool_dependencies FK rows
  are NOT seeded here because Pitchbook tools are registered dynamically (IDs
  vary per deployment). The FK linkage is established when the platform admin
  imports the 92 Pitchbook tools via the Discover flow.
- All skills: scope='platform', status='published', mandatory=false.
- plan_required follows data sensitivity: professional for standard research,
  enterprise for deal/fund/LP financials.
- Prompt templates use {{input.field}} handlebars and stay within 2000 chars.
- Idempotent: ON CONFLICT DO NOTHING on id.
"""
from alembic import op

revision = "v062"
down_revision = "v061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO skills (
            id, name, description, category, version,
            execution_pattern, invocation_mode,
            prompt_template, input_schema, output_schema,
            tool_dependencies, llm_config,
            plan_required, scope, status, mandatory, is_active,
            created_at, updated_at
        ) VALUES

        -- ---------------------------------------------------------------
        -- 1. Company Due Diligence Brief
        --    Primary use case: PE/VC analyst first-look on a target.
        --    Pulls bio, financials, key people, recent deals, latest news.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000001',
            'Company Due Diligence Brief',
            'Generates a structured first-look due diligence brief for a target company using PitchBook data. Covers business overview, financials, deal history, key people, and recent news.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a private equity analyst. Using the PitchBook data retrieved for {{input.company_name}} (PitchBook ID: {{input.pb_id}}), produce a concise due diligence brief.

Structure your response as:
1. Business Overview — what the company does, sector, HQ, founding year, stage
2. Financial Snapshot — revenue, EBITDA, headcount (from most recent financials)
3. Funding History — total raised, investor names, most recent round details
4. Key People — founders and C-suite with relevant background notes
5. Recent Developments — last 30 days news and deal activity
6. Red Flags — any concerns from the data (missing financials, high turnover, etc.)

Be factual. Cite data points. Flag any gaps where PitchBook data is unavailable.',
            '{"type": "object", "properties": {"company_name": {"type": "string", "description": "Company name for context"}, "pb_id": {"type": "string", "description": "PitchBook entity ID (e.g. 12345-67)"}}, "required": ["pb_id", "company_name"]}',
            '{"type": "object", "properties": {"brief": {"type": "string"}, "data_completeness": {"type": "string"}}}',
            '["pitchbook_company_bio", "pitchbook_company_financials", "pitchbook_company_most_recent_financials", "pitchbook_company_deals", "pitchbook_company_most_recent_financing", "pitchbook_entity_people", "pitchbook_entity_news"]',
            '{"temperature": 0.2, "max_tokens": 2000}',
            'enterprise',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 2. Investor Targeting
        --    Use case: Find the right investors for a specific deal or raise.
        --    Pulls investor bios, preferences, last fund, active portfolio.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000002',
            'Investor Targeting',
            'Identifies and profiles investors best suited to a deal or fundraise. Analyses investment preferences, recent fund activity, and portfolio fit against the target criteria.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are an investment banker preparing a targeted investor list. The target company is {{input.company_name}} in the {{input.sector}} sector at the {{input.stage}} stage, seeking {{input.raise_size}}.

Using the PitchBook investor data retrieved, evaluate each investor and produce:
1. Fit Score (High / Medium / Low) — based on sector focus, stage, check size
2. Investment Thesis — their stated focus and recent activity
3. Last Fund — fund name, size, vintage, status
4. Portfolio Overlap — any existing portfolio companies in same sector
5. Recommended Approach — warm intro path or cold outreach rationale

Rank investors from highest to lowest fit. Include only investors with High or Medium fit.',
            '{"type": "object", "properties": {"company_name": {"type": "string"}, "sector": {"type": "string", "description": "Industry sector (e.g. B2B SaaS, Healthcare IT)"}, "stage": {"type": "string", "description": "Funding stage (e.g. Series B, Growth Equity)"}, "raise_size": {"type": "string", "description": "Target raise amount (e.g. $50M)"}, "investor_pb_ids": {"type": "array", "items": {"type": "string"}, "description": "List of PitchBook investor IDs to evaluate"}}, "required": ["company_name", "sector", "stage", "investor_pb_ids"]}',
            '{"type": "object", "properties": {"investor_list": {"type": "array"}, "summary": {"type": "string"}}}',
            '["pitchbook_investor_bio", "pitchbook_investor_investment_preferences", "pitchbook_investor_last_closed_fund", "pitchbook_investor_active_investments", "pitchbook_search_investors"]',
            '{"temperature": 0.2, "max_tokens": 2000}',
            'professional',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 3. Deal Comparable Analysis
        --    Use case: M&A / PE — find and analyse transaction comps.
        --    Pulls deal bios, multiples, valuations for comparable deals.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000003',
            'Deal Comparable Analysis',
            'Finds and analyses comparable M&A and private equity transactions to support valuation work. Returns deal comps with entry multiples, valuations, and deal structure details.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are an M&A analyst building a transaction comps table. The target is a {{input.sector}} company at approximately {{input.target_revenue}} revenue being evaluated for {{input.deal_type}}.

Using the PitchBook deal data retrieved, build a comparable transactions table:

| Company | Deal Date | Deal Type | EV | Revenue | EV/Revenue | EBITDA | EV/EBITDA | Buyer |
|---------|-----------|-----------|-----|---------|------------|--------|-----------|-------|

After the table, provide:
- Median and mean multiples for EV/Revenue and EV/EBITDA
- Implied valuation range for the target at median multiples
- 2-3 most relevant comps with brief rationale
- Any notable outliers and why they should be excluded

Flag deals where financial data is unavailable.',
            '{"type": "object", "properties": {"sector": {"type": "string"}, "target_revenue": {"type": "string", "description": "Approximate target revenue (e.g. $20M ARR)"}, "deal_type": {"type": "string", "description": "Transaction type (e.g. acquisition, growth equity, LBO)"}, "deal_pb_ids": {"type": "array", "items": {"type": "string"}, "description": "PitchBook deal IDs for comparable transactions"}}, "required": ["sector", "deal_type", "deal_pb_ids"]}',
            '{"type": "object", "properties": {"comps_table": {"type": "string"}, "median_multiples": {"type": "object"}, "implied_valuation": {"type": "string"}}}',
            '["pitchbook_deal_bio", "pitchbook_deal_detailed", "pitchbook_deal_multiples", "pitchbook_deal_valuation", "pitchbook_search_deals"]',
            '{"temperature": 0.1, "max_tokens": 2000}',
            'enterprise',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 4. Founder & Executive Profile
        --    Use case: Founder diligence, exec hiring, board research.
        --    Pulls bio, education/work history, contact data.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000004',
            'Founder & Executive Profile',
            'Builds a comprehensive background profile on a founder or executive using PitchBook People data. Covers career history, education, board memberships, and prior venture outcomes.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are conducting executive due diligence on {{input.person_name}} (PitchBook ID: {{input.pb_id}}).

Using the PitchBook people data retrieved, produce a professional profile:

1. Career Trajectory — chronological work history, roles, tenure at each company
2. Education — degrees, institutions, graduation years
3. Prior Venture Outcomes — exits, acquisitions, or failures in their history
4. Board & Advisory Roles — current and past board seats
5. Domain Expertise — industries, functions, geographies with deep experience
6. Notable Observations — patterns that indicate strengths or risks for this role

Write objectively. Distinguish facts (from PitchBook) from inferences. Do not speculate about personal matters.',
            '{"type": "object", "properties": {"person_name": {"type": "string"}, "pb_id": {"type": "string", "description": "PitchBook person ID"}, "context": {"type": "string", "description": "Optional context: role being evaluated, company being diligenced"}}, "required": ["pb_id", "person_name"]}',
            '{"type": "object", "properties": {"profile": {"type": "string"}, "risk_flags": {"type": "array", "items": {"type": "string"}}}}',
            '["pitchbook_people_bio", "pitchbook_people_education_work", "pitchbook_investor_board_memberships"]',
            '{"temperature": 0.2, "max_tokens": 1500}',
            'professional',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 5. Fund Research & Benchmarking
        --    Use case: LP due diligence on a fund manager, or GP benchmarking.
        --    Pulls fund bio, performance, benchmark, LPs, preferences.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000005',
            'Fund Research & Benchmarking',
            'Profiles a private equity or venture fund and benchmarks its performance against peers. Covers fund strategy, IRR/MOIC, portfolio activity, LP base, and quartile ranking.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are an LP analyst evaluating {{input.fund_name}} (PitchBook ID: {{input.pb_id}}) for potential commitment.

Using the PitchBook fund data retrieved, produce a fund research note:

1. Fund Overview — GP name, fund series, vintage year, size, strategy, geography focus
2. Performance Metrics — net IRR, MOIC/TVPI, DPI, RVPI (from PitchBook); note if unaudited
3. Benchmark Comparison — quartile ranking vs peers (same vintage, strategy, size)
4. Portfolio Activity — number of investments, notable holdings, exit count
5. LP Base — type of LPs, concentration, any notable investors
6. Investment Preferences — sector, stage, check size, co-investment policy
7. Assessment — strengths, concerns, key diligence questions for GP meeting

Clearly distinguish reported vs estimated figures.',
            '{"type": "object", "properties": {"fund_name": {"type": "string"}, "pb_id": {"type": "string", "description": "PitchBook fund ID"}}, "required": ["pb_id", "fund_name"]}',
            '{"type": "object", "properties": {"fund_note": {"type": "string"}, "performance_summary": {"type": "object"}}}',
            '["pitchbook_fund_bio", "pitchbook_fund_performance", "pitchbook_fund_benchmark", "pitchbook_fund_investment_preferences", "pitchbook_fund_lps", "pitchbook_fund_portfolio_holdings"]',
            '{"temperature": 0.2, "max_tokens": 2000}',
            'enterprise',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 6. LP Intelligence Brief
        --    Use case: Fundraising — identify and profile target LPs.
        --    Pulls LP bio, commitment preferences, allocations, history.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000006',
            'LP Intelligence Brief',
            'Researches a limited partner for fundraising outreach. Returns commitment preferences, target and actual PE/VC allocations, historical fund commitments, and recommended engagement approach.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are preparing an LP outreach package for {{input.lp_name}} (PitchBook ID: {{input.pb_id}}).

Your fund is: {{input.fund_description}}

Using PitchBook LP data, produce a targeted engagement brief:

1. LP Profile — institution type, AUM, location, investment team contacts
2. Allocation Strategy — target PE/VC allocation (%), current actual allocation, over/under vs target
3. Commitment Preferences — fund size range, GP relationships, co-investment appetite, geographic/strategy constraints
4. Commitment History — recent fund commitments (last 3 years), typical commitment size
5. Fit Assessment — alignment with your fund strategy, size, and geography; HIGH / MEDIUM / LOW
6. Recommended Approach — best contact(s), talking points that match their stated preferences, potential objections to address',
            '{"type": "object", "properties": {"lp_name": {"type": "string"}, "pb_id": {"type": "string", "description": "PitchBook LP ID"}, "fund_description": {"type": "string", "description": "Brief description of your fund (strategy, size, vintage, geography)"}}, "required": ["pb_id", "lp_name", "fund_description"]}',
            '{"type": "object", "properties": {"brief": {"type": "string"}, "fit_score": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]}}}',
            '["pitchbook_lp_bio", "pitchbook_lp_commitment_prefs", "pitchbook_lp_target_allocations", "pitchbook_lp_actual_allocations", "pitchbook_lp_commitments_detailed"]',
            '{"temperature": 0.2, "max_tokens": 1800}',
            'enterprise',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 7. Portfolio Company Monitor
        --    Use case: Weekly digest of news and deal activity for a
        --    portfolio company. Ongoing monitoring, not one-time DD.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000007',
            'Portfolio Company Monitor',
            'Produces a weekly monitoring digest for a portfolio company. Covers recent news, deal activity, operational updates, and flags any material developments requiring GP attention.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a portfolio management associate monitoring {{input.company_name}} (PitchBook ID: {{input.pb_id}}) on behalf of the investment team.

Review the PitchBook updates and news retrieved for the past {{input.lookback_days}} days and produce a monitoring digest:

1. Material Events — any fundraising, M&A, leadership changes, or regulatory news (flag as 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW)
2. Deal Activity — new investments into the company or exits by existing investors
3. People Changes — executive hires, departures, or board changes
4. Market News — industry or competitive news relevant to the company
5. No-change confirmation — if nothing material, state clearly: "No material developments in the monitoring period."

Keep each section to 2-3 sentences. Flag items that require GP follow-up.',
            '{"type": "object", "properties": {"company_name": {"type": "string"}, "pb_id": {"type": "string", "description": "PitchBook entity ID"}, "lookback_days": {"type": "integer", "default": 7, "description": "Number of days to look back (default: 7)"}}, "required": ["pb_id", "company_name"]}',
            '{"type": "object", "properties": {"digest": {"type": "string"}, "requires_attention": {"type": "boolean"}}}',
            '["pitchbook_entity_news", "pitchbook_entity_updates", "pitchbook_company_updates", "pitchbook_company_deals"]',
            '{"temperature": 0.3, "max_tokens": 1000}',
            'professional',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        ),

        -- ---------------------------------------------------------------
        -- 8. Exit Readiness Assessment
        --    Use case: GP assessing a portfolio company for exit timing.
        --    Pulls valuation estimates, VC exit predictions, similar
        --    companies (for strategic buyer mapping), recent deal comps.
        -- ---------------------------------------------------------------
        (
            '00000000-0000-0000-0003-000000000008',
            'Exit Readiness Assessment',
            'Evaluates a portfolio company''s exit readiness using PitchBook predictive data. Assesses valuation range, exit pathway options (strategic M&A, secondary, IPO), and optimal timing signals.',
            'Private Markets Intelligence',
            '1.0.0',
            'tool_composing',
            'llm_invoked',
            'You are a portfolio management partner preparing an exit committee memo for {{input.company_name}} (PitchBook ID: {{input.pb_id}}).

Using PitchBook data, assess exit readiness across three pathways:

**Strategic M&A**
- Valuation estimate range from PitchBook model
- VC exit prediction score (if available) and what drives it
- Similar companies that were acquired — who bought them and at what multiples?
- Likely strategic acquirer categories and rationale

**Financial Sponsor (Secondary / Growth)**
- Current investor base and any investors likely seeking liquidity
- Comparable growth equity or buyout transactions in this sector

**IPO / Direct Listing**
- Revenue scale and growth rate relative to public comps
- Public market sentiment for this sector

**Recommendation**
- Preferred exit pathway with rationale
- Suggested timing window (immediate / 12 months / 18-24 months)
- Key value creation levers before exit

Base all statements on PitchBook data. Flag assumptions clearly.',
            '{"type": "object", "properties": {"company_name": {"type": "string"}, "pb_id": {"type": "string", "description": "PitchBook entity ID"}, "investment_date": {"type": "string", "description": "Optional: date of original investment (e.g. 2022-06)"}, "entry_valuation": {"type": "string", "description": "Optional: entry valuation for return calculation"}}, "required": ["pb_id", "company_name"]}',
            '{"type": "object", "properties": {"memo": {"type": "string"}, "recommended_pathway": {"type": "string"}, "timing": {"type": "string"}}}',
            '["pitchbook_company_vc_exit_predictions", "pitchbook_company_valuation_estimates", "pitchbook_company_similar_companies", "pitchbook_company_all_investors", "pitchbook_company_deals"]',
            '{"temperature": 0.2, "max_tokens": 2000}',
            'enterprise',
            'platform',
            'published',
            false,
            true,
            NOW(),
            NOW()
        )

        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM skills
        WHERE id IN (
            '00000000-0000-0000-0003-000000000001',
            '00000000-0000-0000-0003-000000000002',
            '00000000-0000-0000-0003-000000000003',
            '00000000-0000-0000-0003-000000000004',
            '00000000-0000-0000-0003-000000000005',
            '00000000-0000-0000-0003-000000000006',
            '00000000-0000-0000-0003-000000000007',
            '00000000-0000-0000-0003-000000000008'
        );
        """
    )
