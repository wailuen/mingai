# Model Context Protocol (MCP) Servers

## Overview

MCP servers extend the system with external data source capabilities. During chat interactions, the LLM can invoke MCP tools to retrieve real-time information.

**Current Status**: 9 MCP servers integrated
**Location**: `src/mcp-servers/` (separate Docker containers)
**Protocol**: WebSocket-based Tool calls

---

## Server Inventory

| #   | Server            | Purpose                           | Data Source        | Status |
| --- | ----------------- | --------------------------------- | ------------------ | ------ |
| 1   | Bloomberg MCP     | Financial data, market news       | Bloomberg Terminal | Active |
| 2   | CapIQ MCP         | Credit intelligence, company data | CapIQ              | Active |
| 3   | Perplexity MCP    | Web search                        | Perplexity AI      | Active |
| 4   | Oracle Fusion MCP | ERP data (orders, invoices)       | Oracle Fusion      | Active |
| 5   | AlphaGeo MCP      | Geospatial intelligence           | AlphaGeo           | Beta   |
| 6   | Teamworks MCP     | Project management data           | Teamworks          | Active |
| 7   | PitchBook MCP     | M&A, market intelligence          | PitchBook          | Beta   |
| 8   | Azure AD MCP      | User/group lookups                | Azure Entra ID     | Active |
| 9   | iLevel MCP        | Investment analytics              | iLevel             | Active |

---

## Bloomberg MCP

**Purpose**: Financial market data, company metrics, market news

**Tools**:

```
get_company_data(ticker: str, metrics: list[str]) -> dict
  - ticker: Stock ticker (e.g., "AAPL")
  - metrics: ["price", "pe_ratio", "market_cap", "dividend_yield"]
  Returns: {metric: value, ...}

get_security_description(ticker: str) -> str
  - Returns: Company description, sector, industry

get_market_news(ticker: str, limit: int = 5) -> list[dict]
  - Returns: [{title, date, summary, source}, ...]

get_financial_statements(ticker: str, statement: str) -> dict
  - statement: "income", "balance_sheet", "cash_flow"
  - Returns: Latest financial data
```

**Example Usage**:

```
User: "What's Apple's P/E ratio?"
LLM: Call get_company_data("AAPL", ["pe_ratio", "price"])
MCP: {"pe_ratio": 28.5, "price": 192.30}
LLM: "Apple's P/E ratio is 28.5, trading at $192.30"
```

---

## CapIQ MCP

**Purpose**: Credit intelligence, company analysis, deal data

**Tools**:

```
get_company_profile(ticker: str) -> dict
  Returns: {name, industry, headquarters, employees, revenue}

get_credit_metrics(ticker: str) -> dict
  Returns: {debt_to_equity, interest_coverage, credit_rating}

search_deals(keywords: str, year: int) -> list[dict]
  Returns: [{deal_id, announced_date, target, acquirer, value}]

get_competitor_analysis(ticker: str) -> dict
  Returns: {competitors, market_position, competitive_advantages}
```

---

## Perplexity MCP

**Purpose**: Web search, real-time internet information

**Tools**:

```
search_web(query: str, depth: str = "advanced", limit: int = 5) -> list[dict]
  - depth: "basic" or "advanced"
  - Returns: [{title, url, snippet, date}]

search_news(keywords: str, date_range: str = "7d") -> list[dict]
  - date_range: "1d", "7d", "30d", "all"
  - Returns: [{headline, source, date, link}]

get_latest_on_topic(topic: str) -> list[dict]
  Returns: Most recent articles/news on topic
```

---

## Oracle Fusion MCP

**Purpose**: ERP system data (orders, customers, inventory)

**Tools**:

```
get_customer_info(customer_id: str) -> dict
  Returns: {name, contact, account_manager, credit_limit, history}

get_open_orders(customer_id: str) -> list[dict]
  Returns: [{order_id, date, status, total, line_items}]

get_invoice_details(invoice_id: str) -> dict
  Returns: {amount, date, status, payment_due, line_items}

get_inventory_status(sku: str) -> dict
  Returns: {quantity_on_hand, location, reorder_point, next_shipment}

create_sales_order(customer_id: str, items: list) -> dict
  Returns: {order_id, status, confirmation_number}
```

---

## Azure AD MCP

**Purpose**: User/group lookups, organizational info

**Tools**:

```
get_user_info(email: str) -> dict
  Returns: {id, name, title, department, manager, phone, office}

get_group_members(group_name: str) -> list[dict]
  Returns: [{email, name, title, department}]

search_users(query: str) -> list[dict]
  Returns: Matching users with basic info

get_org_chart(user_email: str) -> dict
  Returns: {user, manager, direct_reports, peers}

get_group_info(group_name: str) -> dict
  Returns: {name, description, owner, member_count, members_list}
```

**Example Usage**:

```
User: "Who is the finance team manager?"
LLM: Call get_group_members("Finance")
MCP: Returns list of Finance team members
LLM: "The Finance team is managed by Sarah Johnson. Current team members are..."
```

---

## Other MCP Servers

### AlphaGeo MCP (Geospatial)

- Location intelligence
- Territory mapping
- Geographic risk assessment

### Teamworks MCP (Project Management)

- Project status
- Team assignments
- Deadlines and milestones
- Resource allocation

### PitchBook MCP (M&A Intelligence)

- Deal tracking
- Company valuations
- Market trends
- Transaction history

### iLevel MCP (Investment Analytics)

- Portfolio performance
- Risk metrics
- Trading data
- Market analysis

---

## MCP Integration with Chat

### Tool Registration

```python
# app/modules/mcp/router.py

mcp_servers = {
    "bloomberg_mcp": {
        "url": "ws://mcp-bloomberg:8000",
        "tools": [
            {
                "name": "get_company_data",
                "description": "Get financial data for a company",
                "parameters": {
                    "ticker": {"type": "string"},
                    "metrics": {"type": "array"}
                }
            },
            ...
        ]
    },
    "azure_ad_mcp": {...},
    "perplexity_mcp": {...},
    ...
}
```

### Tool Invocation During Chat

```python
async def invoke_mcp_tool(
    server_id: str,
    tool_name: str,
    parameters: dict
) -> dict:
    """
    1. Find MCP server config
    2. Connect via WebSocket
    3. Call tool with params
    4. Return result
    5. Stream result chunks
    """

    server = mcp_servers[server_id]
    connection = await connect_websocket(server["url"])

    result = await connection.call_tool(
        tool_name=tool_name,
        parameters=parameters
    )

    return result
```

### LLM Context Injection

```python
# When building prompt for synthesis

tools_context = """
Available External Data Sources:
1. Bloomberg: Get real-time financial data
   - get_company_data(ticker, metrics)
   - get_market_news(ticker)

2. Azure AD: Look up organizational info
   - get_user_info(email)
   - get_group_members(group_name)

3. Perplexity: Search the web
   - search_web(query)
   - search_news(keywords)

You can invoke these tools during your response by:
[TOOL_CALL] bloomberg: get_company_data("AAPL", ["price", "pe_ratio"])

The system will execute the tool and continue your response.
"""

# Include in system prompt
messages = [
    {"role": "system", "content": f"{system_prompt}\n{tools_context}"},
    {"role": "user", "content": user_query}
]
```

### Tool Result Streaming

```
LLM: "[TOOL_CALL] bloomberg: get_company_data('AAPL', ['price'])"
System: Executes tool → {"price": 192.30}
LLM: Resumes: "Apple is trading at $192.30..."
Client: Receives:
  - ["[TOOL_CALL] bloomberg:..."]
  - ["Apple is trading at $192.30"]
```

---

## Authorization & Limits

### Per-Tool Rate Limiting

```python
rate_limits = {
    "bloomberg_mcp.get_company_data": {"calls_per_minute": 30, "calls_per_day": 10000},
    "perplexity_mcp.search_web": {"calls_per_minute": 10, "calls_per_day": 1000},
    "oracle_fusion_mcp.create_sales_order": {"calls_per_day": 100},
}
```

### Tool Access Control

```python
# Some tools require elevated permissions
tool_permissions = {
    "oracle_fusion_mcp.create_sales_order": ["order:create"],
    "get_user_info": ["user:read"],
    "get_group_members": ["user:read", "groups:read"],
}

# Before tool call, check user permissions
if tool_name in tool_permissions:
    required = tool_permissions[tool_name]
    user_perms = get_user_permissions(user_id)
    if not all(p in user_perms for p in required):
        raise HTTPException(403, f"Cannot access {tool_name}")
```

---

## Error Handling

### Tool Failure Fallback

```python
try:
    result = await invoke_mcp_tool(server_id, tool_name, params)
except TimeoutError:
    # Tool took too long
    logger.warning(f"MCP timeout: {server_id}.{tool_name}")
    result = {"error": "Service timeout"}
except ConnectionError:
    # MCP server unavailable
    logger.error(f"MCP server offline: {server_id}")
    result = {"error": "Data source unavailable"}
except Exception as e:
    # Other errors
    logger.error(f"MCP error: {str(e)}")
    result = {"error": "Failed to retrieve data"}

# Include in LLM response
if "error" in result:
    llm_prompt += f"\n\nTool {tool_name} failed: {result['error']}"
    llm_prompt += "\nProvide answer based on your training data."
```

---

## Monitoring

### Tool Call Metrics

```python
metrics = {
    "mcp_tool_calls": 12450,  # This month
    "by_server": {
        "bloomberg_mcp": 5000,
        "azure_ad_mcp": 3500,
        "perplexity_mcp": 2200,
        "oracle_fusion_mcp": 1500,
        "others": 250
    },
    "success_rate": 0.98,
    "avg_latency_ms": 450,
    "errors": {
        "timeout": 180,
        "not_found": 45,
        "auth_failed": 15
    }
}
```

---

## Future Enhancements

### Custom MCP Server Deployment

```
User (Enterprise Admin) → Create new MCP server
→ Register in system
→ Test tools
→ Set permissions
→ Enable for organization
→ Monitor usage

Example: Company registers internal MCP server for HR system
- Tool: get_employee_benefits(employee_id)
- Tool: check_leave_balance(employee_id)
- Permission: employees can only access their own data
```

### Tool Composition

```
Chain multiple tools:
User: "Show me Apple's stock price and latest news"

LLM calls:
1. bloomberg: get_company_data("AAPL", ["price"])
2. perplexity: search_news("Apple AAPL")

Synthesizes both results into single response
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
