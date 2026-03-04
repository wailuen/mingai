# LLM Integration Strategy

## Azure OpenAI Deployments

| Deployment                 | Model        | Purpose                             | Latency | Token Limit |
| -------------------------- | ------------ | ----------------------------------- | ------- | ----------- |
| **aihub2-main**            | GPT-5.2-chat | Chat synthesis, complex reasoning   | 2-5s    | 128K ctx    |
| **intent5**                | GPT-5 Mini   | Intent detection, fast tasks        | <1s     | 128K ctx    |
| **text-embedding-3-large** | Embeddings   | Document & query vectors (3072-dim) | <1s     | N/A         |
| **gpt-vision**             | GPT-5 Vision | Image analysis, document OCR        | 2-3s    | 4K out      |

> **Source**: `config.py` field descriptions explicitly name `gpt-5.2-chat` (primary) and `gpt-5-mini` (intent/auxiliary). `context_window.py` maps these deployment names to 128K context windows. `schemas.py` and `defaults.py` confirm `supports_reasoning_effort=True` for GPT-5 models.

### Configuration

```python
# Primary endpoint
AZURE_OPENAI_ENDPOINT = "https://[resource-name].openai.azure.com/"
AZURE_OPENAI_KEY = "[api-key]"
AZURE_OPENAI_API_VERSION = "2024-12-01-preview"
AZURE_OPENAI_PRIMARY_DEPLOYMENT = "aihub2-main"
AZURE_OPENAI_AUXILIARY_DEPLOYMENT = "intent5"

# Embeddings
AZURE_OPENAI_DOC_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"

# Vision (separate credentials optional)
AZURE_OPENAI_VISION_DEPLOYMENT = "gpt-vision"
AZURE_OPENAI_VISION_ENDPOINT = ""  # uses primary if empty
AZURE_OPENAI_VISION_KEY = ""       # uses primary key if empty
```

---

## LLM Clients

### OpenAI Client (Shared Library)

Located at: `src/backend/shared/aihub_shared/services/openai_client.py`

**Capabilities**:

```python
class AzureOpenAIClient:
    def chat_completion(
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> ChatCompletion | StreamingChatCompletion

    def embeddings(
        input: str | list[str],
        model: str = "text-embedding-3-large"
    ) -> Embedding

    def vision_analysis(
        image_url: str,
        prompt: str,
        max_tokens: int = 1024
    ) -> str
```

### Embeddings Service

Located at: `src/backend/shared/aihub_shared/services/embeddings.py`

**Caching**:

```python
def get_embeddings(text: str) -> list[float]:
    """
    1. Check Redis cache for embedding
    2. If miss: Call Azure OpenAI
    3. Cache result for 1 year
    4. Return embedding (3072 dimensions)
    """
```

---

## Prompt Templates

### System Prompt (Chat)

```
You are an enterprise AI assistant for {company_name}.

Your role:
1. Answer questions using only provided context
2. Cite sources with [Source N]
3. Admit knowledge gaps
4. Maintain professional tone
5. Follow organizational policies

User Profile:
- Name: {user.full_name}
- Department: {user.department}
- Role: {user.job_title}

Instructions:
- Response length: 2-3 paragraphs
- Use bullet points for lists
- Ask 1-2 clarifying follow-ups
- Include source attributions
```

### Intent Detection Prompt

```
Analyze this query and determine:
1. User's intent
2. Most relevant indexes to query
3. Whether internet search needed
4. Query language
5. Urgency level

Available Indexes:
{index_list}

Query: {user_query}

Conversation: {history}

Return JSON:
{
  "intent": "string",
  "selected_indexes": ["id1", "id2"],
  "requires_internet": boolean,
  "language": "en|es|fr|...",
  "urgency": "low|normal|high"
}
```

---

## Cost Optimization

### Token Usage Estimation

```
Average query:
- Intent detection: ~300 tokens (GPT-5 Mini) = $0.001
- Search + synthesis: ~1500 tokens (GPT-5.2-chat) = $0.015
- Total per query: $0.016

Monthly (10,000 queries):
- Cost: ~$160
- Embeddings: ~$40 (cached heavily)
- Total: ~$200
```

### Cost Control Strategies

```
1. Model Selection:
   - GPT-5 Mini for intent (save 90% on intent cost)
   - GPT-5.2-chat for synthesis (quality matters)

2. Token Limits:
   - Max 2000 tokens output per response
   - Summarize conversation history (>5K tokens)
   - Truncate sources to 5 chunks

3. Caching:
   - Cache embeddings (1 year)
   - Cache intent detection results (24 hours)
   - Cache glossary lookups (1 month)

4. Rate Limiting:
   - 10 requests/minute per user
   - 1000 requests/day system-wide
   - Burst allowance: 50 tokens/second
```

---

## Multi-Model Orchestration

### Model Selection Logic

```python
def select_model_for_task(task_type: str, priority: str) -> str:
    """Choose optimal model based on task"""

    model_map = {
        "intent_detection": "intent5",      # Fast, cheap
        "synthesis": "aihub2-main",         # High quality
        "vision_analysis": "gpt-vision",    # Multimodal
        "fast_task": "intent5",             # Quick response
        "complex_reasoning": "aihub2-main"  # Deep analysis
    }

    if priority == "urgent":
        # Use fastest model
        return model_map.get(task_type, "intent5")
    else:
        # Use highest quality
        return model_map.get(task_type, "aihub2-main")
```

### Fallback Chain

```
Primary: GPT-5.2-chat (aihub2-main)
    ↓ (timeout/rate limit)
Fallback 1: GPT-5 Mini (intent5)
    ↓ (still fails)
Fallback 2: Return search results + summary
    ↓ (system overloaded)
Fallback 3: "System busy, try again soon"
```

---

## Prompt Injection Protection

### Input Validation

```python
def sanitize_query(query: str) -> str:
    """
    1. Remove control characters
    2. Limit length to 5000 chars
    3. Detect prompt injection patterns
    4. Log suspicious queries
    """

    # Block patterns
    blocked_patterns = [
        r"ignore.*previous",
        r"forget.*instruction",
        r"system.*prompt",
        r"jailbreak",
        r"forget.*you.*are"
    ]

    for pattern in blocked_patterns:
        if re.search(pattern, query.lower()):
            logger.warning(f"Suspicious input detected: {query[:100]}")
            raise HTTPException(400, "Invalid query")

    return query[:5000]
```

### Output Validation

```python
def validate_response(response: str) -> str:
    """
    1. Check for obvious failures
    2. Verify source citations present
    3. Detect repeated content
    """

    # Check minimum quality
    if len(response) < 50:
        logger.error("Response too short")
        raise ValueError("LLM response insufficient")

    # Verify citations
    if "[Source" not in response:
        logger.warning("No sources cited")
        # Add warning to response
        response = f"{response}\n\n(Note: Response lacks source citations)"

    return response
```

---

## Monitoring & Logging

### Request/Response Logging

```python
def log_llm_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    cost_usd: float,
    user_id: str
):
    """Log all LLM API calls for cost/perf tracking"""

    event = {
        "timestamp": datetime.now(UTC),
        "event_type": "llm_call",
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "user_id": user_id
    }

    # Log to events container
    cosmos_db.events.create_item(event)

    # Track metrics
    metrics.increment("llm.calls", tags=[f"model:{model}"])
    metrics.gauge("llm.latency_ms", latency_ms)
    metrics.gauge("llm.cost_usd", cost_usd)
```

### Cost Tracking

```
Daily aggregation:
- Total API calls: 12,450
- Total tokens: 18.7M
- Total cost: $187.50
- Avg cost/call: $0.015
- By model:
  - GPT-5.2-chat: $150 (80%)
  - GPT-5 Mini: $30 (16%)
  - Embeddings: $7.50 (4%)
```

---

## Future Enhancements

### GPT-5 Migration (TODO-51) — COMPLETED

```
Status: Migration complete. Both deployments now run GPT-5 models.
- aihub2-main → gpt-5.2-chat (128K context)
- intent5 → gpt-5-mini (128K context)

Completed features:
- reasoning_effort parameter support (none/low/medium/high)
- Separate intent endpoint (AZURE_OPENAI_INTENT_ENDPOINT)
- Fallback deployments configured (intent-detection, aihub2-main)
- supports_reasoning_effort flag in model registry

Remaining (from config TODO-51 comments):
- Tune reasoning_effort levels per use case (currently "none" for both)
- Monitor latency vs quality tradeoffs with reasoning enabled
```

### Multi-Modal RAG

```
Enhance document processing:
- Extract images from PDFs
- Generate image descriptions (vision model)
- Index images in search
- Include images in RAG context
- Display images in responses

Example: User asks about "org chart"
- Retrieve org chart image
- Analyze with vision model
- Synthesize text description
- Return both image + text
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
