# 05 — AI Services Implementation Guide

**Start with AI-056 (ChatOrchestrationService) — everything depends on it.**

Read `01-context-loading.md` and the profile/memory architecture docs before implementing.
Port existing implementations from `/Users/wailuen/Development/aihub2` — read before rewriting.

---

## Priority Order

1. **AI-056** `ChatOrchestrationService` — core RAG orchestrator (implement first)
2. **AI-054** `EmbeddingService` — required by ChatOrchestration
3. **AI-055** `VectorSearchService` — required by ChatOrchestration
4. **AI-059** `ConversationPersistenceService` — required by ChatOrchestration
5. **AI-001** `ProfileLearningService` — injected into ChatOrchestration
6. **AI-011** `WorkingMemoryService` — injected into ChatOrchestration
7. **AI-021** `OrgContextService` — injected into ChatOrchestration
8. **AI-031** `GlossaryExpander` — required before LLM call
9. **AI-041** `SystemPromptBuilder` — assembles all 6 layers
10. **AI-051** `TeamWorkingMemoryService` — injected into SystemPromptBuilder

---

## AI-056: ChatOrchestrationService (Most Critical)

`app/modules/chat/orchestrator.py`

This is the core service that wires the entire RAG pipeline. It is the first thing to implement.

```python
import asyncio
from typing import AsyncGenerator
from app.core.config import settings
from app.modules.glossary.expander import GlossaryExpander
from app.modules.chat.prompt_builder import SystemPromptBuilder
from app.modules.chat.embedding import EmbeddingService
from app.modules.chat.vector_search import VectorSearchService
from app.modules.profile.learning import ProfileLearningService
from app.modules.profile.working_memory import WorkingMemoryService
from app.modules.memory.org_context import OrgContextService
from app.modules.teams.team_memory import TeamWorkingMemoryService
from app.modules.chat.persistence import ConversationPersistenceService
from app.modules.chat.confidence import RetrievalConfidenceCalculator

class ChatOrchestrationService:
    """
    8-stage RAG pipeline:
    1. Glossary pre-translation (expand query)
    2. Intent detection (is it a memory command?)
    3. Embedding (original query → vector)
    4. Vector search (parallel per agent's indexes)
    5. Context building (profile, working memory, org context, team memory)
    6. SystemPromptBuilder (6 layers → system prompt)
    7. LLM streaming (with circuit breaker)
    8. Post-processing (confidence score, memory update, persistence)
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_search_service: VectorSearchService,
        profile_service: ProfileLearningService,
        working_memory_service: WorkingMemoryService,
        org_context_service: OrgContextService,
        team_memory_service: TeamWorkingMemoryService,
        glossary_expander: GlossaryExpander,
        prompt_builder: SystemPromptBuilder,
        persistence_service: ConversationPersistenceService,
        confidence_calculator: RetrievalConfidenceCalculator,
    ):
        self._embedding = embedding_service
        self._search = vector_search_service
        self._profile = profile_service
        self._working_memory = working_memory_service
        self._org_context = org_context_service
        self._team_memory = team_memory_service
        self._glossary = glossary_expander
        self._prompt_builder = prompt_builder
        self._persistence = persistence_service
        self._confidence = confidence_calculator

    async def stream_response(
        self,
        query: str,
        user_id: str,
        tenant_id: str,
        agent_id: str,
        conversation_id: str | None,
        active_team_id: str | None,
    ) -> AsyncGenerator[dict, None]:
        """Main entry point: yields SSE-formatted dicts."""

        # Stage 1: Glossary pre-translation
        # RAG embedding uses ORIGINAL query; LLM uses EXPANDED query
        expanded_query, expansions = await self._glossary.expand(query, tenant_id)

        # Stage 2: Intent detection — is this a memory command?
        if self._is_memory_command(query):
            note = await self._handle_memory_command(query, user_id, tenant_id, agent_id)
            yield {"event": "memory_saved", "data": {"note_id": str(note.id), "content": note.content}}
            yield {"event": "done", "data": {"conversation_id": conversation_id, "message_id": None}}
            return

        yield {"event": "status", "data": {"stage": "searching", "message": "Searching knowledge base..."}}

        # Stage 3: Embed ORIGINAL query (not expanded — preserve retrieval accuracy)
        query_vector = await self._embedding.embed(query)

        # Stage 4: Vector search (parallel across agent's indexes)
        search_results = await self._search.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            agent_id=agent_id,
            top_k=10
        )

        yield {"event": "sources", "data": {"sources": [s.to_dict() for s in search_results]}}

        # Stage 5: Build context (parallel fetches)
        yield {"event": "status", "data": {"stage": "building_context", "message": "Building your response..."}}

        profile_ctx, working_mem_ctx, org_ctx, team_mem_ctx = await asyncio.gather(
            self._profile.get_profile_context(user_id, tenant_id),
            self._working_memory.get_context(user_id, tenant_id, agent_id),
            self._org_context.get_context(user_id, tenant_id),
            self._team_memory.get_context(active_team_id, tenant_id) if active_team_id else None,
        )

        # Stage 6: Build system prompt (6 layers)
        system_prompt, layers_active = await self._prompt_builder.build(
            agent_id=agent_id,
            tenant_id=tenant_id,
            org_context=org_ctx,
            profile_context=profile_ctx,
            working_memory=working_mem_ctx,
            team_memory=team_mem_ctx,
            rag_context=search_results,
        )

        if profile_ctx:
            yield {"event": "profile_context_used", "data": {"layers_active": layers_active}}

        # Stage 7: LLM streaming (EXPANDED query goes to LLM)
        model = settings.primary_model  # from .env — never hardcode
        full_response = ""

        async for chunk in self._stream_llm(
            system_prompt=system_prompt,
            user_message=expanded_query,
            model=model
        ):
            full_response += chunk
            yield {"event": "response_chunk", "data": {"text": chunk}}

        # Stage 8: Post-processing
        confidence = self._confidence.calculate(search_results)
        yield {"event": "metadata", "data": {
            "retrieval_confidence": confidence,
            "tokens_used": self._estimate_tokens(system_prompt, expanded_query, full_response),
            "model": model,  # from settings.primary_model — never hardcode
            "glossary_expansions": expansions,
        }}

        # Persist conversation + update working memory + trigger profile learning
        message_id, conv_id = await self._persistence.save_exchange(
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query=query,
            response=full_response,
            sources=search_results,
        )
        await self._working_memory.update(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            query=query,
            response=full_response,
        )
        if active_team_id:
            await self._team_memory.update(
                team_id=active_team_id,
                tenant_id=tenant_id,
                query=query,
            )
        # Trigger profile learning every 10 queries (async — don't block response)
        asyncio.create_task(
            self._profile.on_query_completed(user_id, tenant_id, agent_id)
        )

        yield {"event": "done", "data": {"conversation_id": str(conv_id), "message_id": str(message_id)}}

    def _is_memory_command(self, query: str) -> bool:
        """Fast path: detect 'remember that...' commands. Port regex from aihub2."""
        import re
        patterns = [
            r'^remember\s+that\b',
            r'^please\s+remember\s+that\b',
            r'^note\s+that\b',
            r'^save\s+this:\s*',
        ]
        return any(re.match(p, query.strip(), re.IGNORECASE) for p in patterns)

    async def _handle_memory_command(self, query, user_id, tenant_id, agent_id):
        content = re.sub(r'^(remember\s+that|please\s+remember\s+that|note\s+that|save\s+this:)\s*',
                         '', query.strip(), flags=re.IGNORECASE).strip()
        if len(content) > 200:
            content = content[:200]  # Enforce 200 char limit
        return await self._working_memory.add_note(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=None,  # user-directed notes are global by default
            content=content,
            source="user_directed"
        )
```

---

## AI-054: EmbeddingService

`app/modules/chat/embedding.py`

```python
import hashlib
import json
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.redis_client import get_redis

class EmbeddingService:
    """
    Generates query embeddings with Redis caching (24h TTL).
    Model from .env — never hardcode.
    """

    def __init__(self):
        self._client = AsyncOpenAI()  # reads OPENAI_API_KEY from env
        self._model = settings.embedding_model  # from .env

    async def embed(self, text: str, tenant_id: str = None) -> list[float]:
        """Returns embedding vector. Caches in Redis if tenant_id provided."""
        if tenant_id:
            cache_key = f"mingai:{tenant_id}:embedding_cache:{hashlib.sha256(text.encode()).hexdigest()[:16]}"
            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)

        response = await self._client.embeddings.create(
            model=self._model,
            input=text
        )
        vector = response.data[0].embedding

        if tenant_id:
            await redis.setex(cache_key, 86400, json.dumps(vector))

        return vector
```

---

## AI-055: VectorSearchService

`app/modules/chat/vector_search.py`

```python
from app.core.config import settings
from app.services.search import get_search_client  # CLOUD_PROVIDER abstraction

class VectorSearchService:
    """
    Cloud-agnostic vector search.
    Delegates to OpenSearch / Azure AI Search / Vertex based on CLOUD_PROVIDER.
    """

    def __init__(self):
        self._client = get_search_client(settings.cloud_provider)

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        agent_id: str,
        top_k: int = 10
    ) -> list[SearchResult]:
        """
        Search tenant's document index for this agent.
        Index naming: {tenant_id}-{agent_id} (isolated per tenant per agent).
        """
        index_name = f"{tenant_id}-{agent_id}"
        raw_results = await self._client.knn_search(
            index=index_name,
            vector=query_vector,
            top_k=top_k
        )
        return [
            SearchResult(
                title=r["title"],
                content=r["content"],
                score=r["score"],
                source_url=r.get("source_url"),
                document_id=r["id"]
            )
            for r in raw_results
        ]
```

---

## AI-001: ProfileLearningService

`app/modules/profile/learning.py` — Port from aihub2 with these changes:

1. Replace CosmosDB with DataFlow (PostgreSQL)
2. Add `tenant_id:` prefix to all Redis keys
3. Replace hardcoded `get_intent_openai_client()` with tenant's configured intent model
4. Add `agent_id` parameter stub (Phase 1: global; Phase 2: per-agent)
5. Implement `query_count` write-back (Redis hot counter → PostgreSQL every 10 queries)

```python
import json
from cachetools import LRUCache
from app.core.config import settings
from app.core.redis_client import get_redis

# Port ProfileLRUCache from aihub2 — no changes needed (pure Python)
_profile_l1_cache = LRUCache(maxsize=1000)

EXTRACTION_PROMPT = """
Analyze the following conversation and extract user profile attributes.
Return JSON with: technical_level, communication_style, interests[], expertise_areas[], common_tasks[], memory_notes[].
Only include fields you can confidently infer. Return {} if nothing to extract.
"""

class ProfileLearningService:
    """
    Triggers every 10 queries (or tenant's configured threshold).
    Redis hot counter → PostgreSQL checkpoint every 10 queries.
    Phase 1: global counter per user. Phase 2: per-agent counter.
    """

    async def on_query_completed(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str  # stub for Phase 2
    ):
        """Call after every chat query (async, non-blocking)."""
        redis = get_redis()
        counter_key = f"mingai:{tenant_id}:profile_learning:query_count:{user_id}"

        # Phase 1: global counter (no agent_id suffix)
        count = await redis.incr(counter_key)
        await redis.expire(counter_key, 30 * 24 * 3600)  # 30 days TTL

        trigger_threshold = await self._get_tenant_threshold(tenant_id)

        if count >= trigger_threshold:
            await redis.set(counter_key, 0)  # reset counter
            await self._run_profile_extraction(user_id, tenant_id, agent_id)
            # Write checkpoint to PostgreSQL
            await self._write_query_count_checkpoint(user_id, tenant_id)

    async def get_profile_context(self, user_id: str, tenant_id: str) -> dict | None:
        """Return profile context for system prompt. 200-token budget."""
        # L1: in-process LRU
        l1_key = f"{tenant_id}:{user_id}"
        if l1_key in _profile_l1_cache:
            return _profile_l1_cache[l1_key]

        # L2: Redis
        redis = get_redis()
        l2_key = f"mingai:{tenant_id}:profile_learning:profile:{user_id}"
        cached = await redis.get(l2_key)
        if cached:
            profile = json.loads(cached)
            _profile_l1_cache[l1_key] = profile
            return profile

        # L3: PostgreSQL
        profile = await self._load_from_db(user_id, tenant_id)
        if profile:
            await redis.setex(l2_key, 3600, json.dumps(profile))  # 1 hour TTL
            _profile_l1_cache[l1_key] = profile

        return profile

    async def clear_l1_cache(self, user_id: str):
        """GDPR: clear in-process cache entries for user."""
        keys_to_delete = [k for k in _profile_l1_cache if k.endswith(f":{user_id}")]
        for k in keys_to_delete:
            del _profile_l1_cache[k]

    async def _run_profile_extraction(self, user_id: str, tenant_id: str, agent_id: str):
        """Extract profile attributes from last 10 conversations using intent model."""
        conversations = await self._get_last_n_conversations(user_id, tenant_id, n=10)
        if not conversations:
            return

        intent_model = await self._get_tenant_intent_model(tenant_id)
        # Only send USER queries (not AI responses) to extraction LLM
        # CRITICAL: data residency + purpose limitation — do NOT send full conversation
        user_queries = [
            msg["content"] for conv in conversations
            for msg in conv["messages"] if msg["role"] == "user"
        ]

        client = self._get_llm_client(intent_model)
        response = await client.chat.completions.create(
            model=intent_model,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": json.dumps(user_queries[:30])}  # last 30 queries max
            ],
            response_format={"type": "json_object"}
        )
        extracted = json.loads(response.choices[0].message.content)
        await self._merge_profile(user_id, tenant_id, extracted)
```

---

## AI-011: WorkingMemoryService

`app/modules/profile/working_memory.py` — Port from aihub2 with these changes:

1. Add `mingai:{tenant_id}:` prefix to all Redis keys
2. Add `agent_id` to working memory key (from Day 1 — even in Phase 1)
3. Port `_extract_topics()` unchanged (pure NLP — no deps)
4. Port `format_for_prompt()` unchanged

```python
import json
import re
from datetime import datetime, timedelta
from app.core.redis_client import get_redis

class WorkingMemoryService:
    """
    Session continuity via Redis.
    Key: mingai:{tenant_id}:working_memory:{user_id}:{agent_id}
    TTL: 7 days (configurable 1-30 days by tenant admin in Phase 2)
    Max topics: 5 | Max queries: 3 (100-char truncation)
    """

    RETURNING_USER_THRESHOLD_HOURS = 1

    async def get_context(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str
    ) -> dict | None:
        redis = get_redis()
        key = f"mingai:{tenant_id}:working_memory:{user_id}:{agent_id}"
        raw = await redis.get(key)
        if not raw:
            return None
        memory = json.loads(raw)

        # Check if returning user (gap > 1 hour)
        last_active = datetime.fromisoformat(memory.get("last_active", ""))
        is_returning = (datetime.utcnow() - last_active) > timedelta(hours=self.RETURNING_USER_THRESHOLD_HOURS)
        memory["is_returning_user"] = is_returning

        return memory

    async def update(
        self,
        user_id: str,
        tenant_id: str,
        agent_id: str,
        query: str,
        response: str
    ):
        redis = get_redis()
        key = f"mingai:{tenant_id}:working_memory:{user_id}:{agent_id}"

        existing = json.loads(await redis.get(key) or "{}")
        topics = existing.get("topics", [])
        queries = existing.get("recent_queries", [])

        # Extract and prepend new topics (newest first, cap 5)
        new_topics = self._extract_topics(query + " " + response)
        topics = list(dict.fromkeys(new_topics + topics))[:5]

        # Prepend query (cap 3, 100-char truncation)
        truncated_query = query[:100]
        queries = [truncated_query] + queries[:2]

        memory = {
            "topics": topics,
            "recent_queries": queries,
            "last_active": datetime.utcnow().isoformat(),
        }

        ttl = await self._get_tenant_ttl(tenant_id)  # days → seconds
        await redis.setex(key, ttl * 86400, json.dumps(memory))

    def format_for_prompt(self, memory: dict) -> str:
        """Port directly from aihub2 — no changes needed."""
        if not memory:
            return ""
        parts = []
        if memory.get("topics"):
            parts.append(f"Recent topics: {', '.join(memory['topics'])}")
        if memory.get("recent_queries"):
            parts.append(f"Recent questions: {'; '.join(memory['recent_queries'])}")
        if memory.get("is_returning_user"):
            parts.append("Note: User is returning after a break.")
        return "\n".join(parts)

    def _extract_topics(self, text: str) -> list[str]:
        """Port directly from aihub2 — keyword extraction, no LLM."""
        # Remove common words, extract noun phrases
        # This is pure Python/NLP — no changes needed
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        return list(dict.fromkeys(words))[:5]
```

---

## AI-021: OrgContextService + Sources

`app/modules/memory/org_context.py`

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class OrgContextData(BaseModel):
    job_title: str | None = None
    department: str | None = None
    country: str | None = None
    company: str
    manager_name: str | None = None

class OrgContextSource(ABC):
    @abstractmethod
    async def get_org_context(self, user_id: str, auth_data: dict) -> OrgContextData:
        pass

class AzureADOrgContextSource(OrgContextSource):
    """Port directly from aihub2 org_context.py — reads from MSGraph API."""
    async def get_org_context(self, user_id: str, auth_data: dict) -> OrgContextData:
        # Call MSGraph /me endpoint with user's access token
        # Map fields to OrgContextData
        # Port implementation from aihub2
        ...

class Auth0OrgContextSource(OrgContextSource):
    """Uses Auth0 Management API user profile + per-tenant field mapping."""
    async def get_org_context(self, user_id: str, auth_data: dict) -> OrgContextData:
        # Fetch from Auth0 Management API (token cached via INFRA-061)
        # Apply tenant's configured field mapping
        ...

class OktaOrgContextSource(OrgContextSource):
    """Returns OrgContextData with all fields None — valid zero-data behavior."""
    async def get_org_context(self, user_id: str, auth_data: dict) -> OrgContextData:
        return OrgContextData(company=auth_data.get("company", ""))

class GenericSAMLOrgContextSource(OrgContextSource):
    """Falls back to SAML attribute claims."""
    async def get_org_context(self, user_id: str, auth_data: dict) -> OrgContextData:
        return OrgContextData(
            job_title=auth_data.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/jobtitle"),
            department=auth_data.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/department"),
            company=auth_data.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/organizationname", ""),
        )

class OrgContextService:
    """Cache org context in Redis (24h TTL). Select source from tenant config."""

    async def get_context(self, user_id: str, tenant_id: str) -> OrgContextData | None:
        redis = get_redis()
        cache_key = f"mingai:{tenant_id}:org_context:{user_id}"
        cached = await redis.get(cache_key)
        if cached:
            return OrgContextData.model_validate_json(cached)

        source = await self._get_source_for_tenant(tenant_id)
        auth_data = await self._get_user_auth_data(user_id, tenant_id)
        context = await source.get_org_context(user_id, auth_data)

        await redis.setex(cache_key, 86400, context.model_dump_json())  # 24h TTL
        return context
```

---

## AI-031: GlossaryExpander

`app/modules/glossary/expander.py`

```python
import re
import unicodedata
from app.core.redis_client import get_redis

# Stop-word exclusion list (platform config — never expanded)
STOP_WORDS = frozenset({
    "as", "it", "or", "by", "at", "be", "do", "go", "in",
    "is", "on", "to", "up", "us", "we", "no", "so", "an",
    "am", "my", "of"
})

class GlossaryExpander:
    """
    Inline glossary expansion. Replaces Layer 6 system prompt injection.
    RAG embedding uses ORIGINAL query — only LLM call uses expanded query.

    Rules:
    - First occurrence only (deduplication)
    - full_form length guard: skip if > 50 chars
    - Uppercase-only rule: terms ≤ 3 chars only expand if ALL CAPS in query
    - Stop-word exclusion: never expand STOP_WORDS
    - CJK: use full-width parentheses
    - Longest match wins on ambiguity
    """

    async def expand(
        self,
        query: str,
        tenant_id: str
    ) -> tuple[str, list[str]]:
        """
        Returns (expanded_query, list_of_expansion_descriptions).
        expansions example: ["AL → Annual Leave", "HR → Human Resources"]
        """
        terms = await self._get_terms(tenant_id)
        if not terms:
            return query, []

        expanded = query
        applied = []
        already_expanded = set()

        # Sort by length descending (longest match wins)
        sorted_terms = sorted(terms, key=lambda t: len(t["term"]), reverse=True)

        for term_obj in sorted_terms:
            term = term_obj["term"]
            full_form = term_obj["full_form"]

            # Security guard: skip if full_form > 50 chars
            if len(full_form) > 50:
                continue

            # Stop-word exclusion
            if term.lower() in STOP_WORDS:
                continue

            # Deduplication
            if term.lower() in already_expanded:
                continue

            # Uppercase-only rule for short acronyms
            if len(term) <= 3 and not re.search(rf'\b{re.escape(term.upper())}\b', expanded):
                continue

            # Find first occurrence (case-insensitive)
            is_cjk = self._is_cjk_query(query)
            open_p, close_p = ("（", "）") if is_cjk else ("(", ")")

            pattern = rf'\b{re.escape(term)}\b'
            match = re.search(pattern, expanded, re.IGNORECASE)
            if match:
                replacement = f"{match.group(0)} {open_p}{full_form}{close_p}"
                expanded = expanded[:match.start()] + replacement + expanded[match.end():]
                applied.append(f"{term} → {full_form}")
                already_expanded.add(term.lower())

            # Also check aliases
            for alias in term_obj.get("aliases", []):
                if alias.lower() in STOP_WORDS or alias.lower() in already_expanded:
                    continue
                alias_match = re.search(rf'\b{re.escape(alias)}\b', expanded, re.IGNORECASE)
                if alias_match:
                    replacement = f"{alias_match.group(0)} {open_p}{full_form}{close_p}"
                    expanded = expanded[:alias_match.start()] + replacement + expanded[alias_match.end():]
                    applied.append(f"{alias} → {full_form}")
                    already_expanded.add(alias.lower())

        # Cap at 10 expansions per query
        return expanded, applied[:10]

    def _is_cjk_query(self, text: str) -> bool:
        for char in text:
            if unicodedata.east_asian_width(char) in ('W', 'F'):
                return True
        return False

    async def _get_terms(self, tenant_id: str) -> list[dict]:
        """Fetch terms from Redis cache (1h TTL). Fallback to PostgreSQL."""
        redis = get_redis()
        cache_key = f"mingai:{tenant_id}:glossary:terms"
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
        terms = await self._load_from_db(tenant_id)
        import json
        await redis.setex(cache_key, 3600, json.dumps(terms))
        return terms
```

---

## AI-041: SystemPromptBuilder (6 Layers)

`app/modules/chat/prompt_builder.py`

```python
from app.core.config import settings

class SystemPromptBuilder:
    """
    Assembles the system prompt from 6 layers.
    Token budgets (canonical — never deviate):
      Layer 0: Agent base (~100 tokens, fixed)
      Layer 1: Platform base (~100 tokens, fixed)
      Layer 2: Org Context (100 tokens)
      Layer 3: Profile Context (200 tokens)
      Layer 4a: Individual Working Memory (100 tokens)
      Layer 4b: Team Working Memory (150 tokens)
      Layer 5: RAG Domain Context (remaining budget)
      Layer 6: Glossary (0 tokens — removed, pre-translated)
    Total overhead (2-4b): 550 tokens
    RAG at 2K: 1,450 tokens | RAG at 4K: 3,450 tokens
    """

    LAYER_BUDGETS = {
        "org_context": 100,
        "profile": 200,
        "working_memory": 100,
        "team_memory": 150,
    }

    async def build(
        self,
        agent_id: str,
        tenant_id: str,
        org_context,
        profile_context,
        working_memory,
        team_memory,
        rag_context: list,
        query_budget: int = 2048,
    ) -> tuple[str, list[str]]:
        """Returns (system_prompt, layers_active)."""
        layers = []
        layers_active = []
        overhead = 0

        # Layer 0: Agent base prompt (from tenant admin config)
        agent_prompt = await self._get_agent_prompt(agent_id, tenant_id)
        layers.append(agent_prompt)

        # Layer 1: Platform base (universal standards)
        layers.append(self._platform_base())

        # Layer 2: Org Context (100 tokens)
        if org_context:
            org_text = self._format_org_context(org_context)
            truncated = self._truncate_to_tokens(org_text, self.LAYER_BUDGETS["org_context"])
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("org_context")

        # Layer 3: Profile + memory notes (200 tokens)
        if profile_context:
            profile_text = self._format_profile_context(profile_context)
            truncated = self._truncate_to_tokens(profile_text, self.LAYER_BUDGETS["profile"])
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("profile")

        # Layer 4a: Individual Working Memory (100 tokens)
        if working_memory:
            wm_text = self._format_working_memory(working_memory)
            truncated = self._truncate_to_tokens(wm_text, self.LAYER_BUDGETS["working_memory"])
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("working_memory")

        # Layer 4b: Team Working Memory (150 tokens)
        if team_memory:
            tm_text = self._format_team_memory(team_memory)
            truncated = self._truncate_to_tokens(tm_text, self.LAYER_BUDGETS["team_memory"])
            layers.append(truncated)
            overhead += self._count_tokens(truncated)
            layers_active.append("team_memory")

        # Layer 5: RAG Domain Context (remaining budget)
        rag_budget = query_budget - overhead
        rag_text = self._format_rag_context(rag_context, rag_budget)
        layers.append(rag_text)

        # Layer 6: Glossary — REMOVED (pre-translated inline, 0 tokens in prompt)

        return "\n\n---\n\n".join(filter(None, layers)), layers_active

    def _platform_base(self) -> str:
        return (
            "You are an AI assistant for enterprise knowledge management. "
            "Base your answers on the provided context. "
            "If information is not in the context, say so clearly. "
            "Label confidence as 'retrieval confidence' — this reflects source quality, not answer quality."
        )

    def _format_org_context(self, ctx) -> str:
        parts = [f"Organization: {ctx.company}"]
        if ctx.job_title: parts.append(f"Role: {ctx.job_title}")
        if ctx.department: parts.append(f"Department: {ctx.department}")
        if ctx.manager_name: parts.append(f"Manager: {ctx.manager_name}")
        return "User Context:\n" + "\n".join(parts)

    def _format_profile_context(self, ctx) -> str:
        parts = []
        if ctx.get("technical_level"):
            parts.append(f"Technical level: {ctx['technical_level']}")
        if ctx.get("communication_style"):
            parts.append(f"Communication: {ctx['communication_style']}")
        if ctx.get("memory_notes"):
            notes = ctx["memory_notes"][:5]  # top 5 newest
            parts.append("Known facts: " + "; ".join(n["content"] for n in notes))
        return "User Profile:\n" + "\n".join(parts)

    def _format_team_memory(self, ctx) -> str:
        """Team memory uses anonymous attribution — no user IDs."""
        parts = []
        if ctx.get("topics"):
            parts.append(f"Team topics: {', '.join(ctx['topics'])}")
        if ctx.get("recent_queries"):
            # Attribution: "a team member" — NEVER user ID or name
            queries = [f"a team member asked: {q}" for q in ctx["recent_queries"]]
            parts.append("\n".join(queries))
        return "Team Context:\n" + "\n".join(parts) if parts else ""
```

---

## AI-051: TeamWorkingMemoryService

`app/modules/teams/team_memory.py`

```python
class TeamWorkingMemoryService:
    """
    Shared Redis memory for active team.
    Key: mingai:{tenant_id}:team_memory:{team_id}
    TTL: 7 days (configurable by tenant admin)
    Attribution: ANONYMOUS ONLY — "a team member" (no user ID/name in Redis)
    Topics: union-merge with dedup (cap 10)
    Query history: cap 5 (anonymous attribution)
    """

    async def get_context(self, team_id: str, tenant_id: str) -> dict | None:
        if not team_id:
            return None
        redis = get_redis()
        key = f"mingai:{tenant_id}:team_memory:{team_id}"
        raw = await redis.get(key)
        return json.loads(raw) if raw else None

    async def update(self, team_id: str, tenant_id: str, query: str):
        """Update team memory. Store query anonymously — no user attribution."""
        redis = get_redis()
        key = f"mingai:{tenant_id}:team_memory:{team_id}"
        existing = json.loads(await redis.get(key) or "{}")

        topics = existing.get("topics", [])
        queries = existing.get("recent_queries", [])

        new_topics = self._extract_topics(query)
        # Union-merge with dedup, cap 10
        topics = list(dict.fromkeys(new_topics + topics))[:10]
        # Anonymous attribution — NEVER store user ID or name
        queries = [query[:100]] + queries[:4]  # cap 5

        ttl = await self._get_tenant_ttl(tenant_id)
        await redis.setex(key, ttl * 86400, json.dumps({
            "topics": topics,
            "recent_queries": queries,
        }))
```

---

## AI-053: RetrievalConfidenceCalculator

`app/modules/chat/confidence.py`

```python
class RetrievalConfidenceCalculator:
    """
    Calculates retrieval confidence from search results.
    This is a RAG RETRIEVAL quality signal — NOT answer quality.
    Label in UI: "retrieval confidence"
    """

    def calculate(self, search_results: list) -> float:
        if not search_results:
            return 0.0
        # Weighted average: top result weighted 40%, rest distributed
        scores = [r.score for r in search_results[:5]]
        if len(scores) == 1:
            return round(scores[0], 3)
        weights = [0.4] + [0.6 / (len(scores) - 1)] * (len(scores) - 1)
        return round(sum(s * w for s, w in zip(scores, weights)), 3)
```

---

## AI-059: ConversationPersistenceService

`app/modules/chat/persistence.py`

```python
class ConversationPersistenceService:
    """
    Persists conversation turns to PostgreSQL.
    Creates new conversation if conversation_id is None.
    """

    async def save_exchange(
        self,
        user_id: str,
        tenant_id: str,
        conversation_id: str | None,
        query: str,
        response: str,
        sources: list,
    ) -> tuple[str, str]:
        """Returns (message_id, conversation_id)."""
        # Tenant context set by get_db dependency
        if not conversation_id:
            conv = await self._create_conversation(user_id, tenant_id)
            conversation_id = str(conv.id)

        # Save user message
        user_msg = await self._save_message(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role="user",
            content=query,
        )

        # Save assistant message with metadata
        asst_msg = await self._save_message(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role="assistant",
            content=response,
            retrieval_confidence=RetrievalConfidenceCalculator().calculate(sources),
        )

        return str(asst_msg.id), conversation_id
```
