"""Pitchbook MCP tool definitions.

Each PitchbookTool maps to one Pitchbook API endpoint and carries:
- A JSON Schema ``input_schema`` for parameter validation / documentation.
- An ``endpoint`` pattern with ``{param}`` placeholders for path params.
- An optional ``method`` (defaults to "GET").
- ``tags`` for grouping in the tool catalog.

ENUM_MAPPING and VALID_ENUM_VALUES are ported from the aihub2 reference
implementation to support human-readable value normalisation in the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class PitchbookTool:
    """Definition of a single Pitchbook MCP tool."""

    name: str
    description: str
    input_schema: dict
    tags: list[str]
    endpoint: str
    method: str = "GET"


# ---------------------------------------------------------------------------
# Enum helpers (ported from aihub2 pitchbook_client.py)
# ---------------------------------------------------------------------------

# Valid API codes for enum parameters
VALID_ENUM_VALUES: dict[str, list[str]] = {
    "dealType": ["VC", "PE", "MA", "IPO", "SEED", "SERIES_A", "SERIES_B", "SERIES_C", "SERIES_D", "GROWTH", "LBO"],
    "fundType": ["VC", "BUYOUT", "GROWTH", "RE", "CREDIT", "FOF", "SECONDARIES", "INFRA"],
    "fundStatus": ["Open", "Closed", "Liquidated"],
    "dealStatus": ["Completed", "Pending", "Announced", "Cancelled"],
    "investorType": ["VC", "PE", "CVC", "Angel", "Family Office", "Hedge Fund"],
}

# Mapping from human-readable values to API codes (case-sensitive keys)
ENUM_MAPPING: dict[str, dict[str, str]] = {
    "dealType": {
        "M&A": "MA", "m&a": "MA",
        "Merger": "MA", "merger": "MA",
        "Acquisition": "MA", "acquisition": "MA",
        "Mergers and Acquisitions": "MA",
        "Venture Capital": "VC", "venture capital": "VC", "Venture": "VC",
        "Private Equity": "PE", "private equity": "PE",
        "Initial Public Offering": "IPO", "initial public offering": "IPO",
        "Seed": "SEED", "seed": "SEED", "Seed Round": "SEED", "seed round": "SEED",
        "Series A": "SERIES_A", "series a": "SERIES_A",
        "Series B": "SERIES_B", "series b": "SERIES_B",
        "Series C": "SERIES_C", "series c": "SERIES_C",
        "Series D": "SERIES_D", "series d": "SERIES_D",
        "Growth": "GROWTH", "growth": "GROWTH",
        "Growth Equity": "GROWTH", "growth equity": "GROWTH",
        "Leveraged Buyout": "LBO", "leveraged buyout": "LBO",
        "Buyout": "LBO", "buyout": "LBO",
    },
    "fundType": {
        "Venture Capital": "VC", "venture capital": "VC", "Venture": "VC",
        "Buyout": "BUYOUT", "buyout": "BUYOUT",
        "Leveraged Buyout": "BUYOUT", "leveraged buyout": "BUYOUT",
        "LBO": "BUYOUT",
        "Growth": "GROWTH", "growth": "GROWTH",
        "Growth Equity": "GROWTH", "growth equity": "GROWTH",
        "Real Estate": "RE", "real estate": "RE", "RE": "RE",
        "Credit": "CREDIT", "credit": "CREDIT",
        "Private Credit": "CREDIT", "private credit": "CREDIT",
        "Debt": "CREDIT", "debt": "CREDIT",
        "Fund of Funds": "FOF", "fund of funds": "FOF", "FoF": "FOF",
        "Secondaries": "SECONDARIES", "secondaries": "SECONDARIES",
        "Secondary": "SECONDARIES", "secondary": "SECONDARIES",
        "Infrastructure": "INFRA", "infrastructure": "INFRA", "Infra": "INFRA",
    },
    "fundStatus": {
        "open": "Open", "Open": "Open",
        "Fundraising": "Open", "fundraising": "Open",
        "closed": "Closed", "Closed": "Closed",
        "Final Close": "Closed", "final close": "Closed",
        "liquidated": "Liquidated", "Liquidated": "Liquidated",
        "Wound Down": "Liquidated", "wound down": "Liquidated",
    },
    "dealStatus": {
        "completed": "Completed", "Completed": "Completed",
        "Done": "Completed", "done": "Completed",
        "Closed": "Completed", "closed": "Completed",
        "pending": "Pending", "Pending": "Pending",
        "In Progress": "Pending", "in progress": "Pending",
        "announced": "Announced", "Announced": "Announced",
        "Rumored": "Announced", "rumored": "Announced",
        "cancelled": "Cancelled", "Cancelled": "Cancelled",
        "canceled": "Cancelled", "Canceled": "Cancelled",
        "Failed": "Cancelled", "failed": "Cancelled",
    },
    "investorType": {
        "Venture Capital": "VC", "venture capital": "VC",
        "Venture Capitalist": "VC", "venture capitalist": "VC",
        "Private Equity": "PE", "private equity": "PE",
        "Corporate Venture Capital": "CVC", "corporate venture capital": "CVC",
        "Corporate VC": "CVC", "corporate vc": "CVC", "Corporate": "CVC",
        "Angel": "Angel", "angel": "Angel",
        "Angel Investor": "Angel", "angel investor": "Angel",
        "Family Office": "Family Office", "family office": "Family Office", "FO": "Family Office",
        "Hedge Fund": "Hedge Fund", "hedge fund": "Hedge Fund", "HF": "Hedge Fund",
    },
}


def normalize_enum_value(param_name: str, value: str) -> str:
    """Normalize a human-readable enum value to its Pitchbook API code.

    Examples:
        >>> normalize_enum_value("dealType", "M&A")
        'MA'
        >>> normalize_enum_value("dealType", "VC")  # already valid
        'VC'
        >>> normalize_enum_value("unknown_param", "anything")
        'anything'
    """
    if param_name not in ENUM_MAPPING:
        return value
    if param_name in VALID_ENUM_VALUES and value in VALID_ENUM_VALUES[param_name]:
        return value
    mapping = ENUM_MAPPING[param_name]
    if value in mapping:
        return mapping[value]
    value_lower = value.lower()
    for key, api_code in mapping.items():
        if key.lower() == value_lower:
            return api_code
    return value


# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

_PB_ID = {"type": "string", "description": "The PitchBook unique identifier for the entity"}
_TRAILING_RANGE = {"type": "integer", "description": "Number of days to look back (e.g., 7, 30)"}
_SINCE_DATE = {"type": "string", "description": "Filter by date. Operators: >YYYY-MM-DD, <YYYY-MM-DD, ^YYYY-MM-DD,YYYY-MM-DD"}
_PAGE = {"type": "integer", "description": "Page number for pagination (starts at 1)"}
_PER_PAGE = {"type": "integer", "description": "Number of results per page (default 25)"}

_UPDATE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "pbId": _PB_ID,
        "sinceDate": _SINCE_DATE,
        "trailingRange": _TRAILING_RANGE,
    },
    "required": ["pbId"],
}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

PITCHBOOK_TOOLS: list[PitchbookTool] = [
    # ==================== ENTITY GENERAL ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_entity_people",
        description="Retrieves data about each team member of the specific entity",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["entity"],
        endpoint="/entities/{pbId}/people",
    ),
    PitchbookTool(
        name="pitchbook_entity_locations",
        description="Retrieves data about locations of HQ and alternate offices of the specific entity",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["entity"],
        endpoint="/entities/{pbId}/locations",
    ),
    PitchbookTool(
        name="pitchbook_entity_affiliates",
        description="Retrieves entities affiliated with the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["entity"],
        endpoint="/entities/{pbId}/affiliates",
    ),
    PitchbookTool(
        name="pitchbook_entity_news",
        description="Retrieves news articles for the specific entity. Returns news from the last N days (default 30, max 30). Use trailingRange to specify days or sinceDate for articles after a specific date.",
        input_schema={
            "type": "object",
            "properties": {
                "pbId": _PB_ID,
                "trailingRange": {"type": "integer", "description": "Number of days to look back for news (1-30). Default is 30 if not specified."},
                "sinceDate": {"type": "string", "description": "Return news after this date. Format: >YYYY-MM-DD (e.g., >2025-01-01)"},
            },
            "required": ["pbId"],
        },
        tags=["entity"],
        endpoint="/entities/{pbId}/news",
    ),
    # ==================== COMPANY SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_company_valuation_estimates",
        description="Retrieves valuation estimates for a private company. Returns analyst valuation estimates, methodology used, estimated enterprise value, estimated equity value, confidence intervals, and as-of date.",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/valuation-estimates",
    ),
    PitchbookTool(
        name="pitchbook_company_financials",
        description="Retrieves ALL historical financial data for a company across multiple fiscal years. Returns a list of annual records with revenue, ebitda, netIncome, grossMargin, etc. Use this when you need historical trends or multi-year data.",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/financials",
    ),
    PitchbookTool(
        name="pitchbook_company_bio",
        description="Retrieves key data points about specific company including description, founding date, status, and primary industry",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_company_industries",
        description="Retrieves industries and verticals tagged to the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/industries",
    ),
    PitchbookTool(
        name="pitchbook_company_all_investors",
        description="Retrieves current and former investors of the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/investors",
    ),
    PitchbookTool(
        name="pitchbook_company_deals",
        description="Retrieves all deals of the specific company including financing rounds, M&A, and IPO",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/deals",
    ),
    PitchbookTool(
        name="pitchbook_company_active_investors",
        description="Retrieves current investors of the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/active-investors",
    ),
    PitchbookTool(
        name="pitchbook_company_general_service_providers",
        description="Retrieves service providers hired for general services to the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/general-service-providers",
    ),
    PitchbookTool(
        name="pitchbook_company_deal_service_providers",
        description="Retrieves service providers hired within the deals to the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/deal-service-providers",
    ),
    PitchbookTool(
        name="pitchbook_company_most_recent_financing",
        description="Retrieves last financing details of the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/most-recent-financing",
    ),
    PitchbookTool(
        name="pitchbook_company_most_recent_debt_financing",
        description="Retrieves debt and lender data within the most recent debt financing deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/most-recent-debt-financing",
    ),
    PitchbookTool(
        name="pitchbook_company_vc_exit_predictions",
        description="Returns exit predictions based on PitchBook machine learning. Company needs at least 2 rounds of funding in the past six years.",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/vc-exit-predictions",
    ),
    PitchbookTool(
        name="pitchbook_company_most_recent_financials",
        description="Retrieves key financial data points of the specific company including revenue, EBITDA, and margins",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/most-recent-financials",
    ),
    PitchbookTool(
        name="pitchbook_company_social_analytics",
        description="Retrieves social media and web signals data points of the specific company",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/social-analytics",
    ),
    PitchbookTool(
        name="pitchbook_company_similar_companies",
        description="Retrieves top 10 similar companies/competitors",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["company"],
        endpoint="/companies/{pbId}/similar-companies",
    ),
    # ==================== DEAL SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_deal_bio",
        description="Retrieves key data points about specific deal including deal type, date, size, and status",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_deal_detailed",
        description="Retrieves extended description of the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/detailed",
    ),
    PitchbookTool(
        name="pitchbook_deal_investors_exiters",
        description="Retrieves investors, exiters and sellers within the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/investors/exiters",
    ),
    PitchbookTool(
        name="pitchbook_deal_service_providers",
        description="Retrieves service providers hired within the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/service-providers",
    ),
    PitchbookTool(
        name="pitchbook_deal_valuation",
        description="Retrieves the company's valuation prior and after the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/valuation",
    ),
    PitchbookTool(
        name="pitchbook_deal_stock_info",
        description="Retrieves key data about stock within the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/stock-info",
    ),
    PitchbookTool(
        name="pitchbook_deal_cap_table_history",
        description="Retrieves stock prices values within the specific deal and prior to it",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/cap-table-history",
    ),
    PitchbookTool(
        name="pitchbook_deal_debt_lenders",
        description="Retrieves debt and lender data within the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/debt-lenders",
    ),
    PitchbookTool(
        name="pitchbook_deal_multiples",
        description="Retrieves key financial multiple values of the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/multiples",
    ),
    PitchbookTool(
        name="pitchbook_deal_tranche_info",
        description="Retrieves key data about the tranches of the specific deal",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["deal"],
        endpoint="/deals/{pbId}/tranche-info",
    ),
    # ==================== PEOPLE SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_people_bio",
        description="Retrieves key data points about specific person including name, title, and biography",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["people"],
        endpoint="/people/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_people_education_work",
        description="Retrieves company, deal, fund and advisory roles of the specific person",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["people"],
        endpoint="/people/{pbId}/education-work",
    ),
    PitchbookTool(
        name="pitchbook_people_contact",
        description="Retrieves contact information of the specific person",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["people"],
        endpoint="/people/{pbId}/contact",
    ),
    # ==================== INVESTOR SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_investor_bio",
        description="Retrieves key data points about specific investor including type, AUM, and investment focus",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_investor_active_investments",
        description="Retrieves active investments of the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/active-investments",
    ),
    PitchbookTool(
        name="pitchbook_investor_all_investments",
        description="Retrieves details of completed investments of the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/investments",
    ),
    PitchbookTool(
        name="pitchbook_investor_investment_preferences",
        description="Retrieves key investment preferences of the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/investment-preferences",
    ),
    PitchbookTool(
        name="pitchbook_investor_funds",
        description="Retrieves open and closed funds of the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/funds",
    ),
    PitchbookTool(
        name="pitchbook_investor_last_closed_fund",
        description="Retrieves details of the last closed fund for the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/last-closed-fund",
    ),
    PitchbookTool(
        name="pitchbook_investor_general_service_providers",
        description="Retrieves service providers hired for general services to the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/general-service-providers",
    ),
    PitchbookTool(
        name="pitchbook_investor_deal_service_providers",
        description="Retrieves service providers hired within the deals to the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/deal-service-providers",
    ),
    PitchbookTool(
        name="pitchbook_investor_board_memberships",
        description="Retrieves board seats held by the specific investor",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["investor"],
        endpoint="/investors/{pbId}/board-seats",
    ),
    # ==================== FUND SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_fund_bio",
        description="Retrieves key data points about specific fund including fund size, vintage year, fund type, strategy, status, close dates, and managing investor name/ID",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_fund_performance",
        description="Retrieves the most recent point-in-time performance metrics for a specific fund. Returns netIrr, grossIrr, tvpi, dpi, rvpi, moic, quartile, nav, asOfDate, calledDownPct, distributed, remainingValue. Quartile 1 = top quartile performer.",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/performance",
    ),
    PitchbookTool(
        name="pitchbook_fund_cash_flows",
        description="Retrieves contributed and distributed amounts for the specific fund",
        input_schema={
            "type": "object",
            "properties": {
                "pbId": _PB_ID,
                "period": {"type": "string", "description": "The time period for cash flow data", "enum": ["quarterly", "annual"]},
            },
            "required": ["pbId", "period"],
        },
        tags=["fund"],
        endpoint="/funds/{pbId}/cashflows/{period}",
    ),
    PitchbookTool(
        name="pitchbook_fund_people",
        description="Retrieves data about each team member of the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/team",
    ),
    PitchbookTool(
        name="pitchbook_fund_all_investments",
        description="Retrieves current and former investments made through the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/investments",
    ),
    PitchbookTool(
        name="pitchbook_fund_investment_preferences",
        description="Retrieves key investment preferences of the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/investment-preferences",
    ),
    PitchbookTool(
        name="pitchbook_fund_benchmark",
        description="Retrieves benchmark comparison data for a specific fund against peer group funds. Returns irrBenchmark, tvpiBenchmark, dpiBenchmark, rvpiBenchmark, percentileRank, numberOfFundsInBenchmark. Always call alongside pitchbook_fund_performance for complete analysis.",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/benchmark",
    ),
    PitchbookTool(
        name="pitchbook_fund_active_investments",
        description="Retrieves current investments made through the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/active-investments",
    ),
    PitchbookTool(
        name="pitchbook_fund_service_providers",
        description="Retrieves service providers related to the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/service-providers",
    ),
    PitchbookTool(
        name="pitchbook_fund_lps",
        description="Retrieves limited partners (LPs) who have committed capital to the specific fund",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["fund"],
        endpoint="/funds/{pbId}/commitments",
    ),
    PitchbookTool(
        name="pitchbook_fund_portfolio_holdings",
        description="Retrieves the portfolio company holdings for a fund at a specific reporting period. Parameters: pbId (fund ID), period (format YYYYQn, e.g., 2024Q3).",
        input_schema={
            "type": "object",
            "properties": {
                "pbId": {"type": "string", "description": "PitchBook fund ID"},
                "period": {"type": "string", "description": "Reporting period in format YYYYQn (e.g., 2024Q3, 2023Q4)"},
            },
            "required": ["pbId", "period"],
        },
        tags=["fund"],
        endpoint="/funds/{pbId}/portfolio-holdings/{period}",
    ),
    # ==================== LIMITED PARTNERS SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_lp_bio",
        description="Retrieves key data points about specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_lp_commitment_prefs",
        description="Retrieves key investment preferences of the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/commitment-prefs",
    ),
    PitchbookTool(
        name="pitchbook_lp_commitments_detailed",
        description="Retrieves commitments information related to the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/commitments-detailed",
    ),
    PitchbookTool(
        name="pitchbook_lp_actual_allocations",
        description="Retrieves actual amounts of the portfolios by sectors for the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/actual-allocations",
    ),
    PitchbookTool(
        name="pitchbook_lp_target_allocations",
        description="Retrieves target amounts of the portfolios by sectors for the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/target-allocations",
    ),
    PitchbookTool(
        name="pitchbook_lp_service_providers",
        description="Retrieves service providers hired for services to the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/service-providers",
    ),
    PitchbookTool(
        name="pitchbook_lp_commitment_aggregates",
        description="Retrieves commitments counts to different fund types made by the specific limited partner",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["lp"],
        endpoint="/limited-partners/{pbId}/commitments-aggregates",
    ),
    # ==================== SERVICE PROVIDERS SPECIFIC ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_service_provider_bio",
        description="Retrieves key data points about specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/bio",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_serviced_companies",
        description="Retrieves companies that were serviced by the specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/serviced-companies",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_serviced_investors",
        description="Retrieves investors that were serviced by the specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/serviced-investors",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_serviced_funds",
        description="Retrieves funds that were serviced by the specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/serviced-funds",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_serviced_lps",
        description="Retrieves limited partners that were serviced by the specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/serviced-limited-partners",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_serviced_deals",
        description="Retrieves data about deals and corresponding companies that were serviced by the specific service provider",
        input_schema={"type": "object", "properties": {"pbId": _PB_ID}, "required": ["pbId"]},
        tags=["service_provider"],
        endpoint="/service-providers/{pbId}/serviced-deals",
    ),
    # ==================== CREDIT ANALYSIS ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_credit_news_search",
        description="Retrieves main info about Credit news articles matching specified criteria. Filter by authors, regions, asset classes, topics, or entity names.",
        input_schema={
            "type": "object",
            "properties": {
                "authors": {"type": "string", "description": "Filter by author names (comma-separated)"},
                "regions": {"type": "string", "description": "Filter by region codes (comma-separated)"},
                "assetClasses": {"type": "string", "description": "Filter by asset class codes (comma-separated)"},
                "topics": {"type": "string", "description": "Filter by topic codes (comma-separated)"},
                "issuer": {"type": "string", "description": "Filter by issuer names or pbIds (comma-separated)"},
                "lender": {"type": "string", "description": "Filter by lender names or pbIds (comma-separated)"},
                "sponsor": {"type": "string", "description": "Filter by sponsor names or pbIds (comma-separated)"},
                "sinceDate": {"type": "string", "description": "Filter by date: >YYYY-MM-DD (after) or <YYYY-MM-DD (before)"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["credit"],
        endpoint="/credit-analysis/credit-news/search",
    ),
    PitchbookTool(
        name="pitchbook_credit_news_most_recent",
        description="Retrieves up to 250 of the most recently published articles and their associated descriptions (excluding article content)",
        input_schema={
            "type": "object",
            "properties": {"page": _PAGE},
            "required": [],
        },
        tags=["credit"],
        endpoint="/credit-analysis/credit-news/most-recent",
    ),
    PitchbookTool(
        name="pitchbook_credit_news_article",
        description="Retrieves full article content for a specific article ID",
        input_schema={
            "type": "object",
            "properties": {"articleId": {"type": "string", "description": "The unique identifier for the credit news article"}},
            "required": ["articleId"],
        },
        tags=["credit"],
        endpoint="/credit-analysis/credit-news/{articleId}",
    ),
    PitchbookTool(
        name="pitchbook_credit_news_bulk",
        description="Returns whole information about the specified Credit News articles (bulk call — multiple articleIds in a single request)",
        input_schema={
            "type": "object",
            "properties": {
                "articleIds": {"type": "array", "items": {"type": "string"}, "description": "List of article IDs to retrieve"},
            },
            "required": ["articleIds"],
        },
        tags=["credit"],
        endpoint="/credit-analysis/credit-news",
        method="POST",
    ),
    PitchbookTool(
        name="pitchbook_credit_news_attachment",
        description="Retrieves an exact attachment file for a specific article. Both articleId and attachment filename are required.",
        input_schema={
            "type": "object",
            "properties": {
                "articleId": {"type": "string", "description": "The unique identifier for the credit news article"},
                "name": {"type": "string", "description": "The filename of the attachment to retrieve"},
            },
            "required": ["articleId", "name"],
        },
        tags=["credit"],
        endpoint="/credit-analysis/credit-news/{articleId}/attachment",
    ),
    # ==================== PATENTS ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_patent_search",
        description="Retrieves patents matching the specified criteria for a company. Filter by status, dates, filing authority, or CPC codes.",
        input_schema={
            "type": "object",
            "properties": {
                "pbId": _PB_ID,
                "status": {"type": "string", "description": "Filter by patent status", "enum": ["Active", "Pending", "Inactive"]},
                "publicationDate": {"type": "string", "description": "Filter by publication date: >YYYY-MM-DD, <YYYY-MM-DD, or ^YYYY-MM-DD,YYYY-MM-DD"},
                "firstFilingDate": {"type": "string", "description": "Filter by first filing date: >YYYY-MM-DD, <YYYY-MM-DD, or ^YYYY-MM-DD,YYYY-MM-DD"},
                "filingAuthorityLocation": {"type": "string", "description": "Filter by filing authority location codes (comma-separated)"},
                "cpcSectionCode": {"type": "string", "description": "Filter by CPC section codes (comma-separated)"},
                "cpcClassCode": {"type": "string", "description": "Filter by CPC class codes (comma-separated)"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": ["pbId"],
        },
        tags=["patent"],
        endpoint="/companies/{pbId}/patents/search",
    ),
    PitchbookTool(
        name="pitchbook_patent_detailed",
        description="Retrieves extended description of the specific patent",
        input_schema={
            "type": "object",
            "properties": {"patentId": {"type": "string", "description": "The unique identifier for the patent"}},
            "required": ["patentId"],
        },
        tags=["patent"],
        endpoint="/companies/patents/{patentId}/detailed",
    ),
    PitchbookTool(
        name="pitchbook_patent_file_download",
        description="Retrieves an exact file of a specific patent",
        input_schema={
            "type": "object",
            "properties": {"patentId": {"type": "string", "description": "The unique identifier for the patent"}},
            "required": ["patentId"],
        },
        tags=["patent"],
        endpoint="/companies/patents/{patentId}/download",
    ),
    # ==================== SEARCH ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_search",
        description="General search to find companies, investors, funds, LPs, and people by name. Best tool for finding entities when you know the name (e.g., 'Stripe', 'Sequoia Capital'). Returns matching entities with their pbId.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The name or search term to find (e.g., 'Stripe', 'Sequoia Capital')"},
                "perPage": {"type": "integer", "description": "Number of results per page (default: 10, max: 100)"},
                "page": _PAGE,
            },
            "required": ["query"],
        },
        tags=["search"],
        endpoint="/search",
    ),
    PitchbookTool(
        name="pitchbook_search_companies",
        description="Advanced company search with filters for industry, location, funding, etc. Use 'pitchbook_search' first to find companies by name — this tool is for filtered searches.",
        input_schema={
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Search keywords in name or description"},
                "industry": {"type": "string", "description": "Filter by industry code (e.g., 'B2B', 'B2C', 'TMT')"},
                "verticals": {"type": "string", "description": "Filter by vertical code"},
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "totalRaised": {"type": "string", "description": "Total funding raised. Operators: >, <, ^. Amounts in millions"},
                "dealSize": {"type": "string", "description": "Deal size. Operators: >, <, ^. Amounts in millions"},
                "dealDate": {"type": "string", "description": "Deal date. Format: YYYY-MM-DD"},
                "revenue": {"type": "string", "description": "Revenue filter. Operators: >, <, ^. Amounts in millions"},
                "employeeCount": {"type": "string", "description": "Employee count. Operators: >, <, ^"},
                "investorNames": {"type": "string", "description": "Find portfolio companies of a specific investor"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/companies/search",
    ),
    PitchbookTool(
        name="pitchbook_search_investors",
        description="Search for investors (VC, PE, corporate, etc.) using various filters including type, AUM, location, and investment preferences.",
        input_schema={
            "type": "object",
            "properties": {
                "investorType": {
                    "type": "string",
                    "description": "Filter by investor type",
                    "enum": ["VC", "PE", "CVC", "ANGEL", "FAMILY_OFFICE", "HEDGE_FUND", "BANK", "ASSET_MANAGER", "GOVERNMENT"],
                },
                "aum": {"type": "string", "description": "AUM filter. Operators: >, <, ^. Amounts in millions"},
                "dryPowder": {"type": "string", "description": "Dry powder filter. Operators: >, <, ^. Amounts in millions"},
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "verticalsPreferences": {"type": "string", "description": "Filter by vertical preference code"},
                "geographicalPreferences": {"type": "string", "description": "Filter by geographic investment preference"},
                "preferredDealTypes": {"type": "string", "description": "Filter by preferred deal type code"},
                "preferredInvestmentAmount": {"type": "string", "description": "Preferred investment size. Operators: >, <, ^. Amounts in millions"},
                "dealVerticals": {"type": "string", "description": "Filter by verticals they have actually invested in"},
                "companyNames": {"type": "string", "description": "Find investors in a specific company"},
                "limitedPartnerNames": {"type": "string", "description": "Find investors backed by a specific LP"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/investors/search",
    ),
    PitchbookTool(
        name="pitchbook_search_deals",
        description="Search for deals (financing rounds, M&A, IPOs, etc.). Use 'keywords' parameter to filter by deal type (e.g., 'M&A', 'acquisition', 'IPO', 'Series A').",
        input_schema={
            "type": "object",
            "properties": {
                "companyNames": {"type": "string", "description": "Find deals for a specific company"},
                "investorNames": {"type": "string", "description": "Find deals by a specific investor"},
                "dealSize": {"type": "string", "description": "Deal size. Operators: >, <, ^. Amounts in millions"},
                "dealDate": {"type": "string", "description": "Deal date. Format: YYYY-MM-DD"},
                "industry": {"type": "string", "description": "Filter by industry"},
                "verticals": {"type": "string", "description": "Filter by verticals"},
                "keywords": {"type": "string", "description": "Search keywords in deal data. Use to filter by deal type (e.g., 'M&A', 'Series A') or industry"},
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "preMoneyValuation": {"type": "string", "description": "Pre-money valuation. Operators: >, <, ^. Amounts in millions"},
                "postValuation": {"type": "string", "description": "Post-money valuation. Operators: >, <, ^. Amounts in millions"},
                "partialExit": {"type": "boolean", "description": "Filter for deals with partial exits"},
                "fullExit": {"type": "boolean", "description": "Filter for deals with full exits"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/deals/search",
    ),
    PitchbookTool(
        name="pitchbook_search_funds",
        description="Search for funds by investor. NOTE: Only investorNames works for filtering. For fund type/vintage/performance filtering use pitchbook_search with keywords.",
        input_schema={
            "type": "object",
            "properties": {
                "investorNames": {"type": "string", "description": "Find funds managed by a specific investor. Primary search parameter."},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/funds/search",
    ),
    PitchbookTool(
        name="pitchbook_search_people",
        description="Search for people (executives, investors, board members) using various filters.",
        input_schema={
            "type": "object",
            "properties": {
                "firstName": {"type": "string", "description": "Filter by first name"},
                "lastName": {"type": "string", "description": "Filter by last name"},
                "biography": {"type": "string", "description": "Search keywords in biography"},
                "positionTitle": {"type": "string", "description": "Filter by position title keywords"},
                "university": {"type": "string", "description": "Filter by university or educational institution"},
                "verticals": {"type": "string", "description": "Filter by vertical of their current company"},
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "email": {"type": "string", "description": "Filter by email address"},
                "domain": {"type": "string", "description": "Filter by email domain"},
                "status": {"type": "string", "description": "Filter by position status (e.g., 'active', 'former')"},
                "gender": {"type": "string", "description": "Filter by gender"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/people/search",
    ),
    PitchbookTool(
        name="pitchbook_search_lps",
        description="Search for limited partners (LPs) such as pension funds, endowments, foundations, and family offices.",
        input_schema={
            "type": "object",
            "properties": {
                "aum": {"type": "string", "description": "AUM filter. Operators: >, <, ^. Amounts in millions"},
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "numberOfCommitments": {"type": "string", "description": "Number of fund commitments. Operators: >, <, ^"},
                "commitmentSize": {"type": "string", "description": "Commitment size. Operators: >, <, ^. Amounts in millions"},
                "commitmentDate": {"type": "string", "description": "Commitment date. Format: YYYY-MM-DD"},
                "fundType": {
                    "type": "string",
                    "description": "Fund type code of committed funds",
                    "enum": ["VC", "BUYOUT", "GROWTH", "RE", "CREDIT", "FOF", "SECONDARIES", "INFRA"],
                },
                "fundCountry": {"type": "string", "description": "Country of committed funds"},
                "currentlyAllocated": {"type": "string", "description": "Current allocation. Operators: >, <, ^. Amounts in millions"},
                "targetedMin": {"type": "string", "description": "Minimum target allocation. Operators: >, <, ^. Amounts in millions"},
                "targetedMax": {"type": "string", "description": "Maximum target allocation. Operators: >, <, ^. Amounts in millions"},
                "mandateKeywords": {"type": "string", "description": "Keywords in the LP's investment mandate"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/limited-partners/search",
    ),
    PitchbookTool(
        name="pitchbook_search_service_providers",
        description="Search for service providers (law firms, accounting firms, investment banks, consultants) using various filters.",
        input_schema={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Filter by city"},
                "stateProvince": {"type": "string", "description": "Filter by state or province"},
                "country": {"type": "string", "description": "Filter by country"},
                "hiredForGeneralServices": {"type": "boolean", "description": "Filter for providers hired for general/ongoing services"},
                "hiredForFundraising": {"type": "boolean", "description": "Filter for providers hired for fundraising activities"},
                "hiredForDealWork": {"type": "boolean", "description": "Filter for providers hired for deal-related work"},
                "numberOfDeals": {"type": "string", "description": "Number of deals serviced. Operators: >, <, ^"},
                "dealSize": {"type": "string", "description": "Deal size of serviced deals. Operators: >, <, ^. Amounts in millions"},
                "dealDate": {"type": "string", "description": "Deal date of serviced deals. Format: YYYY-MM-DD"},
                "companyIndustry": {"type": "string", "description": "Industry of companies they have serviced"},
                "companyVerticals": {"type": "string", "description": "Verticals of companies they have serviced"},
                "page": _PAGE,
                "perPage": _PER_PAGE,
            },
            "required": [],
        },
        tags=["search"],
        endpoint="/service-providers/search",
    ),
    # ==================== PROFILE UPDATES ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_entity_updates",
        description="Retrieves changes/updates for a generic entity. Only use when entity type is unknown — prefer type-specific update tools for companies, investors, funds, people, deals, LPs, or service providers.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/entities/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_company_updates",
        description="Retrieves changes/updates for a specific company during a timeframe. Tracks changes to company profile including financials, funding, employees, status.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/companies/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_investor_updates",
        description="Retrieves changes/updates for a specific investor during a timeframe. Tracks new investments, fund launches, AUM changes.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/investors/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_deal_updates",
        description="Retrieves changes/updates for a specific deal during a timeframe. Tracks valuation updates, investor additions, status changes.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/deals/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_people_updates",
        description="Retrieves changes/updates for a specific person during a timeframe. Tracks job changes, board appointments, contact updates.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/people/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_fund_updates",
        description="Retrieves changes/updates for a specific fund during a timeframe. Tracks performance updates, new investments, closes.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/funds/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_service_provider_updates",
        description="Retrieves changes/updates for a specific service provider during a timeframe. Tracks new clients, deal involvement.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/service-providers/{pbId}/updates",
    ),
    PitchbookTool(
        name="pitchbook_lp_updates",
        description="Retrieves changes/updates for a specific limited partner during a timeframe. Tracks new commitments, allocation changes.",
        input_schema=_UPDATE_PARAMS_SCHEMA,
        tags=["updates"],
        endpoint="/limited-partners/{pbId}/updates",
    ),
    # ==================== STATISTICS / ADMIN ENDPOINTS ====================
    PitchbookTool(
        name="pitchbook_credits_history",
        description="Retrieves credit usage history for the PitchBook API account. Admin-only tool for monitoring API credit consumption.",
        input_schema={"type": "object", "properties": {}, "required": []},
        tags=["statistics"],
        endpoint="/credits/history",
    ),
    PitchbookTool(
        name="pitchbook_calls_costs",
        description="Retrieves API call cost breakdown by pricing model. Admin-only tool for monitoring API costs.",
        input_schema={
            "type": "object",
            "properties": {
                "pricingModel": {
                    "type": "string",
                    "description": "Pricing model filter",
                    "enum": ["SUBSCRIPTION", "PAY_PER_CALL"],
                },
            },
            "required": [],
        },
        tags=["statistics"],
        endpoint="/calls/costs",
    ),
    PitchbookTool(
        name="pitchbook_calls_history",
        description="Retrieves API call history for the PitchBook API account. Admin-only tool for debugging and auditing API usage patterns.",
        input_schema={"type": "object", "properties": {}, "required": []},
        tags=["statistics"],
        endpoint="/calls/history",
    ),
]


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

_TOOL_INDEX: dict[str, PitchbookTool] = {t.name: t for t in PITCHBOOK_TOOLS}


def get_tool(name: str) -> Optional[PitchbookTool]:
    """Return the PitchbookTool with the given name, or None if not found."""
    return _TOOL_INDEX.get(name)
