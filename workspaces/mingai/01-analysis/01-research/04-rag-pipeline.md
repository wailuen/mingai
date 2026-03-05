# RAG Pipeline Deep-Dive

## Pipeline Stages

```
Query → Intent Detection → Index Selection → Vector Search →
Deduplication → Context Building → LLM Synthesis → Confidence Scoring → Response
```

**Total Latency Target**: <3 seconds (observed: 2-3s)

---

## Stage 1: Intent Detection & Index Selection

**Model**: Azure OpenAI GPT-5 Mini (fast, cost-effective)
**Latency**: <1s
**Input**:

- User query
- Available indexes (list with names/descriptions)
- Conversation history (last 3 messages)
- User's organizational context (optional)

**Output**:

```json
{
  "language": "en",
  "intent": "hr_policy_question",
  "intent_confidence": 0.94,
  "selected_indexes": ["hr-policies", "public-kb"],
  "reasoning": "User asking about PTO policy, best answered from HR and general knowledge bases",
  "requires_internet": false,
  "follow_up_question": false,
  "sentiment": "neutral",
  "urgency": "normal"
}
```

**Prompt Template**:

```
You are an intelligent query router for an enterprise knowledge system.

User's Organizational Context:
- Department: Finance
- Job Title: Analyst
- Location: New York

Available Knowledge Bases:
1. HR_Policies: Employee handbook, benefits, time off (450 docs)
2. Finance_Reports: Financial data, budgets, forecasts (320 docs)
3. Engineering_Docs: Technical specs, APIs, architecture (280 docs)
4. Public_KB: General company info, history, values (150 docs)

User's Conversation History:
- Q: "What does our company do?"
- A: "We are a leading financial services..."
- Q: "What's the PTO policy?"

Task: Analyze the current query and select 0-3 most relevant indexes.

Query: {user_query}

Return JSON:
{
  "language": "en|es|fr|...",
  "intent": "brief intent description",
  "intent_confidence": 0.0-1.0,
  "selected_indexes": ["index_id_1", "index_id_2"],
  "reasoning": "why these indexes selected",
  "requires_internet": true|false,
  "follow_up_question": true|false,
  "sentiment": "positive|neutral|negative",
  "urgency": "low|normal|high"
}
```

---

## Stage 2: Parallel Vector Search

**Service**: Azure AI Search (Hybrid search: Vector + Keyword)
**Latency**: <1s (parallel queries)
**Execution**:

```
For each selected index:
  1. Convert query to embedding (Azure OpenAI text-embedding-3-large)
  2. Execute hybrid search in Azure Search
  3. Top K = 5 results per index
  4. Min score threshold = 0.6
  5. Return results in parallel
```

**Query**:

```python
search_results = []
for index_id in selected_indexes:
    # Get index metadata from Cosmos DB
    index = cosmos_db.indexes.read_item(index_id, index_id)

    # Generate query embedding
    embedding = azure_openai.embeddings.create(
        input=user_query,
        model="text-embedding-3-large",
        dimensions=3072
    )

    # Search Azure Search
    results = azure_search.search(
        index_name=index.search_config.index_name,
        search_text=user_query,
        vector_queries=[
            VectorQuery(
                vector=embedding.data[0].embedding,
                k_nearest_neighbors=5,
                fields=["chunk_vector"]
            )
        ],
        top=5,
        search_mode="any",  # BM25 + vector
        query_type="semantic"
    )

    # Score and sort
    scored_results = [
        {
            "index_id": index_id,
            "title": r["doc_title"],
            "chunk_id": r["chunk_id"],
            "content": r["chunk_text"],
            "vector_score": r["@search.score"],  # 0-1
            "keyword_score": r.get("@search.reranker_score", 0)  # BM25
        }
        for r in results
    ]

    search_results.extend(scored_results)
```

**Result Format**:

```json
[
  {
    "index_id": "hr-policies",
    "title": "Employee Handbook - Time Off",
    "chunk_id": "chunk-12345",
    "content": "PTO Policy: Full-time employees receive 20 days of paid time off annually...",
    "vector_score": 0.87,
    "keyword_score": 0.92,
    "combined_score": 0.89,
    "url": "https://sharepoint/sites/HR/Documents/handbook.pdf#chunk-12345"
  }
]
```

---

## Stage 2b: Deduplication & Ranking

**Goal**: Remove duplicate documents, rank by relevance

```python
def deduplicate_and_rank(results):
    """
    1. Group by document title
    2. Keep highest-scoring chunk per document
    3. Sort by combined score
    4. Return top 15-20 total
    """
    doc_map = {}
    for result in results:
        key = result["title"]
        if key not in doc_map or result["combined_score"] > doc_map[key]["combined_score"]:
            doc_map[key] = result

    ranked = sorted(
        doc_map.values(),
        key=lambda x: x["combined_score"],
        reverse=True
    )

    return ranked[:15]  # Top 15 chunks total
```

---

## Stage 3: Context Building

**Goal**: Inject organizational context, user history, glossary

```python
def build_context(user_id, user_query, results):
    """
    1. Load user profile and preferences
    2. Load glossary terms relevant to query
    3. Load conversation history (last 5 messages, summarized)
    4. Format as system context
    """
    # User context
    user = cosmos_db.users.read_item(user_id, user_id)
    user_context = f"""
User Profile:
- Name: {user.full_name}
- Department: {user.department}
- Job Title: {user.job_title}
- Location: {user.office_location}
    """

    # Glossary context
    glossary_matches = []
    for term in extract_terms_from_query(user_query):
        glossary = cosmos_db.glossary_terms.query_items(
            query="SELECT * FROM c WHERE c.term = @term AND c.scope = 'enterprise'",
            parameters=[{"name": "@term", "value": term}]
        )
        if glossary:
            glossary_matches.append(glossary[0].definition)

    glossary_context = ""
    if glossary_matches:
        glossary_context = f"""
Enterprise Glossary:
{chr(10).join([f"- {term}" for term in glossary_matches[:5]])}
    """

    # Conversation history
    history_context = load_conversation_history(user_id, conversation_id, limit=5)

    return {
        "user_context": user_context,
        "glossary_context": glossary_context,
        "history_context": history_context
    }
```

---

## Stage 4: LLM Synthesis (RAG)

**Model**: Azure OpenAI GPT-5.2-chat (mingai-main deployment)
**Latency**: 1-2s
**Token Budget**: 8000 tokens max output

**System Prompt**:

```
You are an enterprise AI assistant helping employees find information and solve problems.

Your core responsibilities:
1. Answer questions based SOLELY on provided context
2. Cite all sources using [Source N] format
3. Acknowledge when information is not available
4. Ask clarifying questions if query is ambiguous
5. Be professional and accurate

Context Quality Rules:
- If sources contradict, acknowledge the contradiction
- If sources are insufficient, say "I don't have enough information"
- If query is outside scope, redirect to appropriate resources
- Always prioritize accuracy over completeness

Response Format:
- Keep responses concise (2-3 paragraphs typical)
- Use bullet points for lists
- Include 1-2 follow-up questions to clarify context
- End with source attribution

Conversation History:
[Previous messages, summarized if >5K tokens]

User Context:
[Organizational profile, preferences]
```

**RAG Prompt Construction**:

```python
def build_rag_prompt(user_query, sources, history, user_context):
    """Construct the final prompt for GPT-5.2-chat"""

    sources_text = "\n\n".join([
        f"[Source {i+1}] {s['title']}\n{s['content'][:500]}..."
        for i, s in enumerate(sources[:5])  # Top 5 sources
    ])

    prompt = f"""
{SYSTEM_PROMPT}

{user_context}

Retrieved Context:
{sources_text}

User Question: {user_query}

Please provide a comprehensive answer based on the sources above.
    """

    return prompt
```

**API Call**:

```python
response = azure_openai.chat.completions.create(
    model="mingai-main",  # GPT-5.2-chat deployment
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.7,
    max_tokens=2000,
    top_p=0.95,
    stream=True  # Stream tokens for real-time UI
)
```

---

## Stage 5: Confidence Scoring

**Goal**: Assess answer quality, transparency to user

```python
def calculate_confidence(query, sources, response, search_metadata):
    """
    Calculate confidence score 0-1 (0=low, 0.5=medium, 1=high)
    """
    scores = {
        "source_agreement": 0.0,
        "vector_similarity": 0.0,
        "coverage": 0.0,
        "text_indicators": 0.0
    }

    # 1. Source Agreement
    # How much do sources agree/corroborate?
    source_variance = np.var([s["vector_score"] for s in sources])
    if source_variance < 0.05:  # Low variance = high agreement
        scores["source_agreement"] = 0.95
    elif source_variance < 0.15:
        scores["source_agreement"] = 0.7
    else:
        scores["source_agreement"] = 0.4

    # 2. Vector Similarity
    # How relevant are the sources to the query?
    avg_similarity = np.mean([s["vector_score"] for s in sources[:3]])
    scores["vector_similarity"] = avg_similarity

    # 3. Coverage
    # Does the response cover all aspects of the query?
    query_aspects = extract_key_phrases(query)
    response_coverage = sum(1 for aspect in query_aspects if aspect.lower() in response.lower())
    scores["coverage"] = min(1.0, response_coverage / max(1, len(query_aspects)))

    # 4. Text Indicators
    # Check for confidence keywords vs uncertainty
    confidence_keywords = ["the policy is", "specifically states", "clearly shows"]
    uncertainty_keywords = ["might be", "possibly", "I don't have"]

    conf_count = sum(1 for kw in confidence_keywords if kw in response.lower())
    unc_count = sum(1 for kw in uncertainty_keywords if kw in response.lower())

    scores["text_indicators"] = max(0, (conf_count - unc_count) / 5)

    # Weighted average
    confidence = (
        scores["source_agreement"] * 0.3 +
        scores["vector_similarity"] * 0.3 +
        scores["coverage"] * 0.2 +
        scores["text_indicators"] * 0.2
    )

    return {
        "overall": confidence,
        "breakdown": scores,
        "level": "HIGH" if confidence > 0.8 else "MEDIUM" if confidence > 0.6 else "LOW"
    }
```

**Confidence Levels**:

- **HIGH** (>0.8): Multiple sources agree, high relevance, clear answer
- **MEDIUM** (0.6-0.8): Good sources, partial coverage
- **LOW** (<0.6): Limited sources, uncertain answer

---

## Stage 6: Response Streaming

**Protocol**: Server-Sent Events (SSE)

```
POST /api/v1/chat/stream
Authorization: Bearer <JWT>

Request:
{
  "conversation_id": "uuid",
  "query": "What is the PTO policy?",
  "index_ids": ["hr-policies"]
}

Response (SSE):
event: status
data: {"stage": "searching", "timestamp": "2026-03-04T10:00:00Z"}

event: sources
data: {"sources": [{"title": "...", "score": 0.87}]}

event: response_chunk
data: {"text": "To address"}

event: response_chunk
data: {"text": " your question"}

event: response_chunk
data: {"text": ", PTO policy is..."}

event: metadata
data: {"confidence": 0.82, "tokens_used": 450, "latency_ms": 2847}

event: done
data: {"message_id": "uuid", "conversation_id": "uuid"}
```

---

## Error Handling & Fallbacks

### Search Failed

```
If Azure Search timeout or no results:
1. Return empty results (confidence = 0)
2. Prompt tells LLM: "No matching documents found"
3. LLM: "I don't have information about this in our knowledge base.
   Please contact [department]."
```

### LLM Generation Failed

```
If GPT-5.2-chat timeout:
1. Try fallback model (GPT-5 Mini)
2. If that fails: Return search results + summary
3. If all fails: "System busy, try again shortly"
```

### Intent Detection Failed

```
If intent detection times out:
1. Use default indexes (public-kb)
2. Search with simple BM25 (no vector)
3. Lower confidence score
```

---

## Optimization Techniques

### Caching

```python
# Cache embeddings for common queries
cache_key = hash(query)
if cache.exists(f"embedding:{cache_key}"):
    embedding = cache.get(f"embedding:{cache_key}")
else:
    embedding = azure_openai.embeddings.create(...)
    cache.setex(f"embedding:{cache_key}", 3600, embedding)
```

### Parallel Execution

```python
# Search multiple indexes in parallel
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = [
        executor.submit(search_index, index)
        for index in selected_indexes
    ]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
```

### Query Expansion

```
If initial search returns <3 results:
1. Expand query with synonyms (glossary lookup)
2. Retry search with expanded query
3. Merge results
```

### Result Truncation

```
If response getting too long:
1. Summarize older sources
2. Keep recent sources full
3. Indicate truncation to user
```

---

## Metrics & Monitoring

### Per-Query Metrics

```json
{
  "query_id": "uuid",
  "user_id": "uuid",
  "timestamp": "2026-03-04T10:00:00Z",
  "intent": "policy_question",
  "indexes_searched": 2,
  "results_count": 5,
  "response_latency_ms": 2847,
  "tokens_used": {
    "input": 1234,
    "output": 567
  },
  "cost_usd": 0.012,
  "confidence": 0.82,
  "user_rating": 5 // 1-5 if provided
}
```

### Aggregated Analytics

```
Daily summaries:
- Total queries: 12,450
- Avg latency: 2.3s
- Avg confidence: 0.79
- Avg user rating: 4.2/5
- Cost: $148.50
- Top intents: [policy_question: 40%, status_check: 25%, ...]
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
