# 03 — AI Services & Intelligence Pipeline Todos

**Scope**: All AI agent, AI service, and intelligence pipeline tasks for mingai
**Plans referenced**: 04 (Issue Reporting), 07 (HAR), 08 (Profile & Memory), 09 (Glossary Pre-Translation)
**Stack**: FastAPI + Kailash Kaizen (BaseAgent) + PostgreSQL (DataFlow) + Redis
**Convention**: All LLM model names read from env config; all Redis keys prefixed `{tenant_id}:`

---

## Profile Learning Service

### AI-001: Port ProfileLRUCache (in-process LRU) ✅ COMPLETED

**Effort**: 1h
**Depends on**: none
**Description**: Port the `ProfileLRUCache` from aihub2 as an in-process LRU cache for user profile data. Phase 1 uses process-local cache only; Phase 2 adds Redis L2 layer.
**Acceptance criteria**:

- [ ] LRU eviction policy with configurable max size (default 256 entries)
- [ ] Cache keyed by `(tenant_id, user_id)` tuple
- [ ] `get()`, `set()`, `invalidate()`, `clear()` methods implemented
- [ ] Thread-safe for concurrent FastAPI request handlers
- [ ] Cache hit/miss counters exposed for observability
      **Notes**: No external dependencies. Single-process only in Phase 1. Phase 2 will add Redis L2 with write-through; design the interface to accept a backend swap.

### AI-002: Port ProfileLearningService with PostgreSQL backend ✅ COMPLETED

**Effort**: 8h
**Depends on**: AI-001, data layer models (user_profiles, profile_learning_events tables must exist)
**Description**: Port `ProfileLearningService` from aihub2 replacing Cosmos DB with DataFlow PostgreSQL backend. Core method: `learn_from_conversations(user_id, tenant_id, agent_id=None)` — fetches last 10 conversations, runs extraction prompt, merges results into user profile.
**Acceptance criteria**:

- [ ] `learn_from_conversations(user_id, tenant_id, agent_id=None)` extracts: interests[], expertise_areas[], technical_level, communication_style, common_tasks[], memory_notes[]
- [ ] Merge strategy for arrays: union-deduplicate with caps (interests=20, expertise_areas=10, common_tasks=15)
- [ ] Merge strategy for technical_level: weighted average with recency bias (most recent 3 conversations weighted 2x)
- [ ] Merge strategy for communication_style: most-recent-wins
- [ ] Stores `profile_learning_event` audit record after each extraction (tenant_id, user_id, event_type, attributes_changed JSONB, timestamp)
- [ ] Invalidates L1 (ProfileLRUCache) and L2 (Redis `{tenant_id}:profile:{user_id}`) after profile update
- [ ] All DataFlow queries filter by tenant_id (multi-tenant isolation)
- [ ] Handles empty conversation history gracefully (no-op, no error)
      **Notes**: The extraction prompt is ported separately in AI-003. Conversation fetch requires the conversations table/service to exist.

### AI-003: Port EXTRACTION_PROMPT template ✅ COMPLETED

**Effort**: 0.5h
**Depends on**: none
**Description**: Port the `EXTRACTION_PROMPT` from aihub2 that instructs the LLM to extract profile attributes from conversation history. Output must be structured JSON matching the profile schema.
**Acceptance criteria**:

- [ ] Prompt extracts all 6 attribute categories (interests, expertise_areas, technical_level, communication_style, common_tasks, memory_notes)
- [ ] Prompt instructs LLM to output valid JSON only
- [ ] Prompt includes cap guidance (interests max 20, expertise max 10, tasks max 15, notes max 5 per extraction)
- [ ] Prompt sends only user queries to extraction LLM (NOT AI responses) to satisfy data minimization
- [ ] Prompt stored as module constant, not hardcoded inline
      **Notes**: Data minimization fix from red team R-critique: aihub2 sent full conversation (user + AI) to extraction LLM. mingai must send user queries only.

### AI-004: Tenant LLM profile selection for intent model slot ✅ COMPLETED

**Effort**: 3h
**Depends on**: AI-002
**Description**: Profile learning extraction uses the tenant's configured intent model from `tenant_settings.llm_profile`. If the tenant's intent model has a context window < 16K tokens, fall back to the platform default intent model.
**Acceptance criteria**:

- [ ] Read tenant's intent model from `tenant_settings.llm_profile` JSONB field
- [ ] Validate context window >= 16K tokens for extraction task (10 conversations can be large)
- [ ] Fallback to platform default intent model (from env `DEFAULT_INTENT_MODEL`) if tenant model insufficient
- [ ] Log a warning when fallback is triggered (include tenant_id, attempted model, reason)
- [ ] Model name never hardcoded; always resolved from tenant config or env
      **Notes**: Replaces aihub2's hardcoded `get_intent_openai_client()` call.

### AI-005: Tenant-scoped Redis keys for profile learning ✅ COMPLETED

**Effort**: 2h
**Depends on**: AI-002
**Description**: All Redis keys used by ProfileLearningService must be prefixed with `{tenant_id}:` to ensure multi-tenant isolation.
**Acceptance criteria**:

- [ ] Profile cache key: `{tenant_id}:profile:{user_id}`
- [ ] Query counter key: `{tenant_id}:profile_learning:query_count:{user_id}` (Phase 1: no agent suffix)
- [ ] All Redis operations use tenant-scoped keys exclusively
- [ ] No Redis key exists without tenant_id prefix
- [ ] Integration test confirms two tenants with same user_id have isolated data
      **Notes**: Phase 2 adds agent suffix to query counter key.

### AI-006: Query counter with Redis hot counter and PostgreSQL write-back ✅ COMPLETED

**Effort**: 2h
**Depends on**: AI-005
**Description**: Implement the query counter that triggers profile learning every 10 queries. Uses Redis as hot counter with periodic write-back to PostgreSQL for durability.
**Acceptance criteria**:

- [ ] `INCR` Redis key `{tenant_id}:profile_learning:query_count:{user_id}` atomically on each query
- [ ] When counter reaches 10: reset to 0, write-back `user_profiles.query_count += 10` to PostgreSQL, launch async learning job
- [ ] On Redis cache miss (cold start / eviction): seed counter from `user_profiles.query_count % 10`
- [ ] Counter increment is atomic (no race conditions with concurrent requests)
- [ ] Write-back uses a single UPDATE with atomic increment (not read-modify-write)
      **Notes**: Phase 1 counter is global (cross-agent). Phase 2 Sprint 9 switches to per-agent counter with key `{tenant_id}:profile_learning:query_count:{user_id}:{agent_id}`.

### AI-007: on_query_completed hook ✅ COMPLETED

**Effort**: 2h
**Depends on**: AI-006
**Description**: Implement `on_query_completed(user_id, tenant_id, agent_id)` hook that fires after every successful chat query. Increments counter and conditionally triggers profile learning.
**Acceptance criteria**:

- [ ] Called at end of chat query pipeline (after response sent to user)
- [ ] Checks `tenant_settings.profile_learning_enabled` before any work; no-op if disabled
- [ ] Calls counter increment (AI-006)
- [ ] When counter triggers: dispatches async profile learning job (background task, not blocking response)
- [ ] Passes `agent_id` parameter (Phase 1: ignored in counter key; Phase 2: used for per-agent scoping)
- [ ] Handles Redis connection failure gracefully (log error, do not fail the query)
      **Notes**: This hook must never block the user's chat response. Use FastAPI BackgroundTasks or equivalent.

### AI-008: Profile learning unit tests (30 tests)

**Effort**: 6h
**Depends on**: AI-002, AI-003, AI-004, AI-006, AI-007
**Description**: Port and adapt 32 aihub2 profile learning tests for PostgreSQL backend. Target 30 passing tests with 100% coverage of ProfileLearningService.
**Acceptance criteria**:

- [ ] 30 unit tests passing
- [ ] Coverage: learn_from_conversations happy path, empty history, merge strategies (array union, dedup, cap enforcement), technical_level weighted average, communication_style most-recent-wins
- [ ] Coverage: query counter increment, counter reset at 10, write-back to PostgreSQL, Redis miss seeding
- [ ] Coverage: tenant LLM profile selection, fallback to default, context window check
- [ ] Coverage: cache invalidation (L1 + L2) after profile update
- [ ] Coverage: tenant_settings.profile_learning_enabled=false → no-op
- [ ] Coverage: concurrent counter increments (race condition test)
- [ ] All tests use real PostgreSQL (DataFlow in-memory or test database); Tier 1 mocking allowed for LLM calls only
      **Notes**: LLM extraction calls may be mocked in Tier 1 unit tests. Integration tests (AI-040) use real LLM.

---

## Working Memory Service

### AI-009: Port WorkingMemoryService with agent-scoped Redis keys ✅ COMPLETED

**Effort**: 3h
**Depends on**: none
**Description**: Port `WorkingMemoryService` from aihub2 with tenant and agent scoping in Redis keys from Day 1. Agent ID comes from the chat request context.
**Acceptance criteria**:

- [ ] Redis key: `{tenant_id}:working_memory:{user_id}:{agent_id}` with TTL=7 days (default)
- [ ] `update(user_id, tenant_id, agent_id, query, response)` — extract topics, append query to recent_queries
- [ ] `get(user_id, tenant_id, agent_id)` returns Dict with topics: list[str], recent_queries: list[str], last_session_at: datetime
- [ ] `clear(user_id, tenant_id, agent_id)` — deletes the Redis key (GDPR erasure)
- [ ] TTL configurable per tenant (Phase 2: 1-30 days range); Phase 1: fixed 7 days
- [ ] Redis key TTL refreshed on every `update()` call
      **Notes**: Unlike aihub2 which used a global key, mingai scopes to agent from Day 1 per plan 08 Sprint 3.

### AI-010: Working memory topic extraction ✅ COMPLETED

**Effort**: 1h
**Depends on**: AI-009
**Description**: Implement `_extract_topics(text)` — keyword extraction from query text using English stop-word filtering.
**Acceptance criteria**:

- [ ] Removes English stop words (standard NLTK-equivalent list)
- [ ] Extracts top 5 keywords by frequency/position
- [ ] New topics prepended to existing topics list
- [ ] Total topics capped at 5 (oldest evicted)
- [ ] Handles empty/whitespace-only text gracefully
- [ ] No external NLP library required (simple tokenization + stop-word filter)
      **Notes**: English-only in Phase 1. Known gap for multinational deployments; semantic upgrade planned for Phase 3.

### AI-011: Working memory format_for_prompt ✅ COMPLETED

**Effort**: 0.5h
**Depends on**: AI-009
**Description**: Implement `format_for_prompt(working_memory, gap_seconds)` that formats working memory data into a string suitable for Layer 4a system prompt injection.
**Acceptance criteria**:

- [ ] Gap < 3600s (1 hour): no "returning user" signal; show last query only; output like "Recent context: [last query truncated to 100 chars]"
- [ ] Gap 3600s-604800s (1 hour to 7 days): "Returning user" signal + last 2 queries + topics
- [ ] Gap > 604800s (7+ days): return empty string (expired session — blank slate)
- [ ] Output fits within 100-token Layer 4a budget
- [ ] Handles None/empty working_memory gracefully (returns empty string)
- [ ] Recent queries truncated to 100 chars each
      **Notes**: Direct port from aihub2. No changes to logic.

### AI-012: Working memory unit tests (50 tests) ✅ COMPLETED

**Effort**: 5h
**Depends on**: AI-009, AI-010, AI-011
**Description**: Port and adapt 72 aihub2 working memory tests. Target 50 passing tests covering all WorkingMemoryService functionality.
**Acceptance criteria**:

- [ ] 50 unit tests passing
- [ ] Coverage: update (new key creation, existing key update, TTL refresh)
- [ ] Coverage: topic extraction (stop words, cap at 5, prepend order, empty input)
- [ ] Coverage: get (existing key, missing key, expired key)
- [ ] Coverage: format_for_prompt (all 3 gap ranges, empty memory, truncation)
- [ ] Coverage: clear (key deletion, idempotent on missing key)
- [ ] Coverage: agent-scoped isolation (same user, different agents have separate memory)
- [ ] Coverage: tenant-scoped isolation (same user+agent across tenants isolated)
- [ ] All tests use real Redis (Tier 1 allowed to use fakeredis; Tier 2 uses real Redis)
      **Notes**: 72 aihub2 tests consolidated to 50 by removing duplicates and Cosmos-specific tests.

---

## Team Working Memory Service

### AI-013: TeamWorkingMemoryService core ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 8h
**Depends on**: AI-009
**Description**: Implement `TeamWorkingMemoryService` for shared team-level working memory. Team members' queries contribute to a shared context pool, anonymized to protect individual privacy.
**Acceptance criteria**:

- [ ] Redis key: `{tenant_id}:team_memory:{team_id}` with TTL=7 days
- [ ] `update(team_id, tenant_id, query, response)` — union-merge topics (cap 10), append anonymized query
- [ ] Anonymized query format: "a team member asked: {query_truncated_to_100_chars}" (cap 5 queries)
- [ ] NEVER stores user_id or display name in team memory Redis value
- [ ] `get(team_id, tenant_id)` returns topics: list[str], recent_queries_anonymous: list[str]
- [ ] `clear(team_id, tenant_id)` — team admin can clear; requires team_admin or tenant_admin role
- [ ] Topics union-merge: combine new topics with existing, deduplicate, cap at 10
      **Notes**: team_id sourced from Azure AD Groups (design documented in Plan 08 Sprint 10). For Phase 1, team_id is passed from the caller; team identity resolution is a separate task.

### AI-014: Team working memory format_for_prompt ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 1h
**Depends on**: AI-013
**Description**: Implement `format_for_prompt(team_memory)` that formats team working memory for Layer 4b injection.
**Acceptance criteria**:

- [ ] Output fits within 150-token Layer 4b budget
- [ ] Format: "Your team has been discussing: [topics]. Recent team questions: [anonymized queries]"
- [ ] Handles empty team memory (returns empty string — Layer 4b skipped)
- [ ] No user identification information in output
      **Notes**: Layer 4b is only injected if the user has an active team assignment. Skip entirely if no active team.

### AI-015: Team working memory unit tests (30 tests)

**Effort**: 5h
**Depends on**: AI-013, AI-014
**Description**: Comprehensive tests for TeamWorkingMemoryService.
**Acceptance criteria**:

- [ ] 30 unit tests passing
- [ ] Coverage: update (new team, existing team, topic merge, query cap, anonymization)
- [ ] Coverage: get (existing team, missing team)
- [ ] Coverage: clear (deletion, role authorization check)
- [ ] Coverage: format_for_prompt (with data, empty data, token budget fit)
- [ ] Coverage: privacy (no user_id or display name leaks in stored data or formatted output)
- [ ] Coverage: topic deduplication and cap at 10
- [ ] Coverage: tenant isolation (same team_id across tenants is isolated)
      **Notes**: Privacy tests are critical. Scan all stored Redis values for user_id patterns.

---

## Org Context Service

### AI-016: OrgContextData Pydantic model ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 1h
**Depends on**: none
**Description**: Define the normalized data model for organizational context attributes extracted from SSO providers.
**Acceptance criteria**:

- [ ] Pydantic model with fields: job_title (Optional[str]), department (Optional[str]), country (Optional[str]), company (str, required), manager_name (Optional[str])
- [ ] Validation: company field is required and non-empty
- [ ] Serialization to/from JSON for Redis caching
- [ ] `to_prompt_text()` method that formats as natural language (~100 tokens target)
- [ ] Handles all-None optional fields gracefully (outputs company-only context)
      **Notes**: Actual aihub2 usage was ~70 tokens, well under 500 budget. We budget 100 tokens for this layer.

### AI-017: OrgContextSource abstract interface ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Depends on**: AI-016
**Description**: Define the abstract interface that all SSO-specific org context sources must implement.
**Acceptance criteria**:

- [ ] Abstract method: `async get_org_context(user_id: str, tenant_id: str, token_claims: dict) -> OrgContextData`
- [ ] Abstract method: `async refresh_on_login(user_id: str, tenant_id: str, new_claims: dict) -> OrgContextData`
- [ ] Concrete method: `get_cached_or_fetch(user_id, tenant_id, token_claims)` — checks Redis first, falls back to `get_org_context()`
- [ ] Redis cache key: `{tenant_id}:org_context:{user_id}` with TTL=24h
- [ ] Cache invalidated on login event (new JWT received)
      **Notes**: Redis cache is mandatory for all sources to shield upstream rate limits (especially Auth0 Management API).

### AI-018: Auth0OrgContextSource implementation ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Depends on**: AI-017
**Description**: Implement Auth0-specific org context source. JWT-first approach: parse claims from the access token. If claims are incomplete, fall back to Auth0 Management API.
**Acceptance criteria**:

- [ ] Primary: extract org context from JWT claims (no API call needed)
- [ ] Per-tenant field mapping config read from `tenant_settings.auth0_field_mapping` JSONB
- [ ] Default mapping: `{ "job_title": "job_title", "department": "department", "country": "locale", "company": "org_name", "manager_name": "manager" }`
- [ ] Fallback: Auth0 Management API call if any mapped field missing from JWT
- [ ] Auth0 API credentials read from env (`AUTH0_MGMT_CLIENT_ID`, `AUTH0_MGMT_CLIENT_SECRET`, `AUTH0_DOMAIN`)
- [ ] Rate limiting: max 10 Management API calls per minute per tenant (tracked in Redis)
- [ ] Redis cache mandatory: `{tenant_id}:org_context:{user_id}` TTL=24h
- [ ] Cache invalidated when new JWT received (login event)
      **Notes**: Replaces aihub2's Azure AD-specific implementation. Auth0 is the primary SSO provider for mingai.

### AI-019: OktaOrgContextSource implementation ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Depends on**: AI-017
**Description**: Implement Okta org context source as a valid zero-data class. All fields return None except company (extracted from JWT). Full Okta API integration deferred to Phase 2.
**Acceptance criteria**:

- [ ] Returns `OrgContextData` with company extracted from JWT `org` claim; all other fields None
- [ ] Does NOT raise NotImplementedError (this is valid zero-data behavior, not a stub)
- [ ] Logs info-level message: "Okta org context: JWT-only mode (API integration available in Phase 2)"
- [ ] Caches result in Redis (same pattern as Auth0)
- [ ] No Okta API calls made in Phase 1
      **Notes**: Per no-stubs rule, this is a valid implementation that returns correct zero-data. It is NOT a placeholder.

### AI-020: GenericSAMLOrgContextSource implementation ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: AI-017
**Description**: Implement SAML attribute-based org context source. Extracts org context from SAML assertion attributes passed via the identity provider.
**Acceptance criteria**:

- [ ] Parses SAML attribute claims from `token_claims` dict
- [ ] Per-tenant SAML attribute mapping in `tenant_settings.saml_field_mapping` JSONB
- [ ] Default SAML mapping: `{ "job_title": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/jobtitle", "department": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/department", ... }`
- [ ] Handles missing attributes gracefully (None for missing fields)
- [ ] Caches result in Redis (same pattern as other sources)
      **Notes**: Fallback source when tenant uses a non-Auth0/non-Okta SAML provider.

### AI-021: OrgContextService (source selector) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Depends on**: AI-018, AI-019, AI-020
**Description**: Service that selects the appropriate org context source based on the tenant's SSO configuration and builds the Layer 2 prompt text.
**Acceptance criteria**:

- [ ] Reads `tenant_settings.sso_provider` to select source (auth0 | okta | saml | none)
- [ ] If sso_provider=none: returns OrgContextData with company from tenant name, all else None
- [ ] Calls selected source's `get_cached_or_fetch()` method
- [ ] Returns formatted prompt text (~100 tokens) via `OrgContextData.to_prompt_text()`
- [ ] Handles source errors gracefully (log error, return empty context, do not fail query)
      **Notes**: This is the single entry point for the SystemPromptBuilder's Layer 2.

### AI-022: Org context unit tests (15 per source, 45 total)

**Effort**: 4h
**Depends on**: AI-018, AI-019, AI-020, AI-021
**Description**: Unit tests for all org context sources and the service selector.
**Acceptance criteria**:

- [ ] 15 tests for Auth0OrgContextSource (JWT parsing, field mapping, API fallback, cache, rate limiting, cache invalidation)
- [ ] 15 tests for OktaOrgContextSource (zero-data behavior, company extraction, caching)
- [ ] 15 tests for GenericSAMLOrgContextSource (SAML claim parsing, custom mapping, missing attributes)
- [ ] Tests for OrgContextService source selection, fallback on error, sso_provider=none
- [ ] All tests use real Redis for caching verification
      **Notes**: Auth0 Management API calls mocked in Tier 1 (external service). Tier 2 integration tests against real Auth0 test tenant are separate.

---

## Memory Notes Service

### AI-023: Memory notes CRUD service ✅ COMPLETED

**Effort**: 4h
**Depends on**: memory_notes DataFlow model
**Description**: Implement memory notes service with all CRUD operations against PostgreSQL via DataFlow.
**Acceptance criteria**:

- [ ] `add_memory_note(user_id, tenant_id, content, source, agent_id=None)` — inserts note; if count > tenant limit (default 15), deletes oldest note(s) to make room
- [ ] `delete_memory_note(note_id, user_id, tenant_id)` — deletes with tenant scope check; returns 404 if note belongs to different tenant
- [ ] `get_memory_notes(user_id, tenant_id, agent_id=None)` — returns List[MemoryNote] newest first; top 5 returned for prompt injection
- [ ] `clear_memory_notes(user_id, tenant_id)` — deletes ALL notes for user in tenant (GDPR erasure)
- [ ] **200-char limit on note content enforced server-side** (reject with 400 if exceeded)
- [ ] `source` field tracks origin: "user" (manual), "auto" (extraction), "team_admin" (Phase 2)
- [ ] All queries filter by tenant_id (multi-tenant isolation)
      **Notes**: 200-char limit was documented in aihub2 but NOT enforced in source code. mingai MUST enforce server-side.

### AI-024: Chat router "remember that" fast path

**Effort**: 2h
**Depends on**: AI-023
**Description**: Implement regex-based intent detection in the chat router for memory note creation. When user says "remember that...", bypass LLM call and directly create a memory note.
**Acceptance criteria**:

- [ ] Regex matches variations: "remember that", "remember:", "please remember", "note that", "save this:"
- [ ] Case-insensitive matching
- [ ] Extracts content after the trigger phrase
- [ ] Calls `add_memory_note()` with source="user"
- [ ] Returns SSE event `memory_saved` with note content (no LLM call)
- [ ] If content exceeds 200 chars, returns error SSE event with message
- [ ] Falls through to normal LLM pipeline if regex does not match
      **Notes**: This is a latency optimization. User gets instant confirmation instead of waiting for LLM round-trip.

### AI-025: Memory notes unit tests (14 tests)

**Effort**: 4h
**Depends on**: AI-023, AI-024
**Description**: Unit tests for memory notes service and chat fast path.
**Acceptance criteria**:

- [ ] 14 unit tests passing
- [ ] Coverage: add note (happy path, cap enforcement with pruning, 200-char limit rejection)
- [ ] Coverage: delete note (own note, cross-tenant rejection, non-existent note)
- [ ] Coverage: get notes (ordering by newest, top 5 for prompt, agent_id filtering)
- [ ] Coverage: clear notes (all deleted, idempotent on empty)
- [ ] Coverage: "remember that" fast path (matching, non-matching, 200-char rejection, SSE event)
- [ ] Coverage: source field correctly set for manual vs auto notes
      **Notes**: Port from aihub2 test suite with PostgreSQL adaptation.

---

## Glossary Expander

### AI-026: GlossaryExpander.expand() core implementation ✅ COMPLETED

**Effort**: 4h
**Depends on**: glossary_terms table and Redis cache (existing infrastructure)
**Description**: Implement `GlossaryExpander.expand(query: str, tenant_id: str) -> tuple[str, list[str]]` that performs inline query expansion using tenant glossary terms.
**Acceptance criteria**:

- [ ] Returns (expanded_query, list_of_applied_expansions) tuple
- [ ] Match algorithm: exact match + alias match, case-insensitive, longest-match-wins
- [ ] Multi-word term matching supported (e.g., "machine learning" matches before "learning")
- [ ] Ambiguity handling: skip expansion if multiple glossary entries match the same query token
- [ ] CJK support: use full-width parentheses for CJK script queries (Unicode block detection)
- [ ] Deduplication: expand first occurrence only; subsequent occurrences of same term left unchanged
- [ ] Full_form length guard: skip expansion if full_form > 50 characters
- [ ] Max 10 expansions per query
      **Notes**: Reads glossary terms from Redis cache `{tenant_id}:glossary:terms` (already populated by glossary CRUD service).

### AI-027: Glossary stop-word exclusion and uppercase rule ✅ COMPLETED

**Effort**: 2h
**Depends on**: AI-026
**Description**: Implement safety rules to prevent false-positive glossary expansions on common English words and short acronyms.
**Acceptance criteria**:

- [ ] Stop-word exclusion list (hardcoded, platform config): "as, it, or, by, at, be, do, go, in, is, on, to, up, us, we, no, so, an, am, my, of"
- [ ] Terms matching any stop word are never expanded regardless of glossary entry
- [ ] Uppercase-only rule for terms with 3 or fewer characters: only expand if the token appears in ALL CAPS in the query (e.g., "IT" expands, "it" does not)
- [ ] Both rules apply before any expansion logic
      **Notes**: Prevents "it" -> "Information Technology" false positive, which was a known issue in early glossary designs.

### AI-028: Glossary pipeline integration ✅ COMPLETED

**Effort**: 4h
**Depends on**: AI-026, AI-027
**Description**: Wire GlossaryExpander into the chat preprocessing pipeline and remove Layer 6 from SystemPromptBuilder.
**Acceptance criteria**:

- [ ] GlossaryExpander runs AFTER intent detection in the query pipeline
- [ ] RAG embedding generation uses the ORIGINAL query (pre-expansion) to preserve retrieval accuracy
- [ ] LLM synthesis call uses the EXPANDED query
- [ ] `glossary_term_matched` analytics event fires for each expansion (preserved from existing analytics)
- [ ] `glossary_expansions_applied` field added to query response metadata (list of expansions)
- [ ] Layer 6 (glossary injection) REMOVED from SystemPromptBuilder
- [ ] Token budget documentation updated (500 tokens freed)
      **Notes**: This is a fundamental change to the query pipeline. The glossary no longer consumes system prompt tokens.

### AI-029: "Terms interpreted" UI indicator

**Effort**: 3h
**Depends on**: AI-028
**Description**: Display a "Terms interpreted" indicator below every chat response where glossary expansions were applied. Mandatory from Day 1 per Plan 09.
**Acceptance criteria**:

- [ ] Indicator appears below the response text when >= 1 expansion applied
- [ ] Shows count: "N terms interpreted" (clickable)
- [ ] Click expands to show full list: "API -> Application Programming Interface"
- [ ] Hidden when no expansions applied
- [ ] Styled per Obsidian Intelligence design system (subtle, not intrusive)
      **Notes**: Frontend component. Backend delivers expansion list via SSE metadata.

### AI-030: Glossary expander unit tests (20 tests)

**Effort**: 4h
**Depends on**: AI-026, AI-027
**Description**: Comprehensive unit tests for GlossaryExpander covering all edge cases.
**Acceptance criteria**:

- [ ] 20 unit tests passing
- [ ] Coverage: exact match, alias match, case-insensitive matching
- [ ] Coverage: multi-word terms, longest-match-wins ordering
- [ ] Coverage: ambiguity (multiple matches -> skip)
- [ ] Coverage: CJK full-width parentheses
- [ ] Coverage: deduplication (first occurrence only)
- [ ] Coverage: full_form > 50 chars -> skip
- [ ] Coverage: stop-word exclusion (all 21 words tested)
- [ ] Coverage: uppercase-only rule for <= 3 char terms
- [ ] Coverage: max 10 expansions cap
- [ ] Coverage: empty query, query with no matches, query with all stop words
      **Notes**: No LLM dependency. Pure string manipulation logic.

### AI-031: Glossary pipeline integration tests (10 tests)

**Effort**: 4h
**Depends on**: AI-028
**Description**: Integration tests verifying the full pipeline: query -> intent detection -> glossary expansion -> RAG (original) + LLM (expanded).
**Acceptance criteria**:

- [ ] 10 integration tests passing
- [ ] Verify RAG embedding receives original (unexpanded) query
- [ ] Verify LLM receives expanded query
- [ ] Verify analytics events fire correctly
- [ ] Verify response metadata includes expansion list
- [ ] Verify Layer 6 is absent from system prompt
- [ ] Verify rollout flag `glossary_pretranslation_enabled` controls behavior
- [ ] Uses real PostgreSQL and Redis; LLM calls may be mocked in Tier 2
      **Notes**: Rollout flag enables gradual tenant migration.

---

## System Prompt Builder

### AI-032: SystemPromptBuilder with 6-layer architecture ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 6h
**Depends on**: AI-009, AI-013, AI-021, AI-023
**Description**: Implement `SystemPromptBuilder` that assembles the system prompt from 6 layers. All layer data fetched in parallel via `asyncio.gather()`.
**Acceptance criteria**:

- [ ] Layer 0: Agent base prompt (from agent config, always present)
- [ ] Layer 1: Platform base (universal safety/standards, always present)
- [ ] Layer 2: Org Context (~100 tokens, from OrgContextService)
- [ ] Layer 3: Profile Context (~200 tokens: technical_level, communication_style, top 5 memory notes newest first)
- [ ] Layer 4a: Individual Working Memory (~100 tokens, agent-scoped)
- [ ] Layer 4b: Team Working Memory (~150 tokens, only if user has active team; skip if no team)
- [ ] Layer 5: Domain Context (RAG content, gets remaining token budget)
- [ ] Layer 6: REMOVED (glossary handled by pre-translation in pipeline)
- [ ] All layer fetches run in parallel via `asyncio.gather()` for minimum latency
- [ ] Each layer returns empty string if data unavailable (graceful degradation)
      **Notes**: Layer 5 (RAG) budget = total_budget - sum(Layer 0-4b actual usage). RAG context is NEVER truncated by the memory system.

### AI-033: Token budget enforcement and truncation priority ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Depends on**: AI-032
**Description**: Implement token budget enforcement with a defined truncation priority order when the total system prompt exceeds the configured budget.
**Acceptance criteria**:

- [ ] Per-layer token limits enforced (configurable per tenant, defaults from Plan 08 Section 4)
- [ ] Truncation priority order (first truncated first): 1. Working memory, 2. Memory notes (oldest first, keep newest 3), 3. Interests (keep top 5), 4. Org context (hard limit 200 tokens)
- [ ] RAG context (Layer 5) is NEVER truncated by the memory system
- [ ] Token counting uses tiktoken (or equivalent) for accurate measurement
- [ ] Truncation events logged at WARN level with layer name and tokens removed
- [ ] Total budget configurable per tenant via `tenant_settings.system_prompt_budget` (default 2048)
      **Notes**: At 2K budget: ~1,450 tokens for RAG after memory overhead. At 4K: ~3,450 tokens for RAG.

### AI-034: Profile SSE flag and memory_saved event

**Effort**: 3h
**Depends on**: AI-032
**Description**: Add SSE metadata flags to chat responses indicating when profile/memory layers contributed to the system prompt.
**Acceptance criteria**:

- [ ] SSE metadata includes `profile_context_used: true` when any profile layer (Layer 2, 3, 4a, or 4b) contributed non-empty content
- [ ] SSE `memory_saved` event emitted when "remember that" fast path creates a note (from AI-024)
- [ ] Frontend `ProfileIndicator` component shows when profile_context_used=true
- [ ] SSE metadata includes list of active layers for debugging (dev mode only)
      **Notes**: Enables user transparency about personalization. Required by Plan 08 Sprint 6.

### AI-035: GDPR clear_profile_data comprehensive erasure ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Depends on**: AI-002, AI-009, AI-023
**Description**: Implement `clear_profile_data(user_id, tenant_id)` that wipes ALL user memory data across all stores. Fixes the aihub2 bug where working memory persisted after erasure.
**Acceptance criteria**:

- [ ] Deletes `user_profiles` row for (user_id, tenant_id)
- [ ] Deletes all `memory_notes` rows for (user_id, tenant_id)
- [ ] Deletes all `profile_learning_events` rows for (user_id, tenant_id)
- [ ] Deletes Redis profile cache: `{tenant_id}:profile:{user_id}`
- [ ] Deletes Redis working memory: `{tenant_id}:working_memory:{user_id}:*` (all agent-scoped keys)
- [ ] Deletes Redis query counter: `{tenant_id}:profile_learning:query_count:{user_id}`
- [ ] Invalidates L1 in-process cache entry for (tenant_id, user_id)
- [ ] All deletions wrapped in a transaction (PostgreSQL) and pipeline (Redis) for atomicity
- [ ] Returns confirmation with count of records deleted per store
- [ ] **CRITICAL**: Working memory deletion MUST be included (fixes aihub2 GDPR bug where `clear_profile_data()` did NOT call `WorkingMemoryService.clear_memory()`)
      **Notes**: This is a GDPR critical path. The aihub2 bug (R04 from red team 13-05) caused working memory to persist 7 days after erasure request.

### AI-036: System prompt builder integration tests (25 tests)

**Effort**: 6h
**Depends on**: AI-032, AI-033, AI-034, AI-035
**Description**: Integration tests for the full SystemPromptBuilder pipeline.
**Acceptance criteria**:

- [ ] 25 integration tests passing
- [ ] Coverage: all 6 layers populated correctly
- [ ] Coverage: individual layers missing (graceful degradation)
- [ ] Coverage: token budget enforcement (over-budget triggers truncation)
- [ ] Coverage: truncation priority order (working memory first, then notes, then interests)
- [ ] Coverage: RAG context never truncated
- [ ] Coverage: parallel fetch (asyncio.gather completes)
- [ ] Coverage: profile_context_used SSE flag (true when layers active, false when empty)
- [ ] Coverage: GDPR clear_profile_data (all stores wiped, working memory included)
- [ ] Coverage: team memory skipped when no active team
- [ ] Coverage: tenant-specific token budgets override defaults
- [ ] Uses real PostgreSQL and real Redis
      **Notes**: LLM calls not involved in prompt building; these tests are infrastructure-only.

---

## Issue Triage Agent

### AI-037: IssueTriageAgent Kaizen BaseAgent implementation

**Effort**: 6h
**Depends on**: issue_reports table, Redis Stream `issue_reports:incoming`
**Description**: Implement the Issue Triage Agent using Kaizen BaseAgent architecture. Consumes from Redis Stream, classifies issues, and routes them appropriately.
**Acceptance criteria**:

- [ ] Extends Kaizen `BaseAgent` with signature-based I/O
- [ ] Consumes from Redis Stream `issue_reports:incoming` (consumer group pattern)
- [ ] Classifies issue type: RAG quality | agent behavior | platform bug | feature request
- [ ] Assesses urgency: critical | high | medium | low (based on error type, user context, frequency)
- [ ] Routes: platform bugs -> platform admin queue; agent behavior -> tenant admin queue; feature requests -> product backlog (NOT bug queue)
- [ ] Model read from env: `TRIAGE_MODEL` (never hardcoded)
- [ ] Timeout: 120 seconds; fallback to P3/bug default if triage times out
- [ ] Max retries: 3 with exponential backoff
      **Notes**: The triage agent does NOT see screenshot content (privacy). Only metadata (`has_screenshot: bool`).

### AI-038: Issue triage confidence scoring and routing rules

**Effort**: 3h
**Depends on**: AI-037
**Description**: Implement confidence scoring for triage decisions and special routing rules.
**Acceptance criteria**:

- [ ] Triage decision includes confidence score (0.0-1.0)
- [ ] If confidence < 0.7: flag issue for human review (do not auto-route)
- [ ] "Still happening" auto-escalation: max 1 escalation per fix deployment
- [ ] Second "still happening" occurrence for same issue -> route to human review (not auto-escalate again)
- [ ] Feature request type: skip severity classification; route directly to product backlog channel
- [ ] Screenshot handling: only `has_screenshot: bool` passed to LLM context; NEVER screenshot content or URL
- [ ] Updates `issue_reports` table with triage result (type, severity, confidence, routed_to, triage_reasoning)
      **Notes**: Privacy is critical. The LLM must never see screenshot image data.

### AI-039: Issue triage agent unit tests (15 tests)

**Effort**: 4h
**Depends on**: AI-037, AI-038
**Description**: Unit tests for the Issue Triage Agent.
**Acceptance criteria**:

- [ ] 15 unit tests passing
- [ ] Coverage: classification for each issue type (RAG quality, agent behavior, platform bug, feature request)
- [ ] Coverage: severity assessment (critical, high, medium, low)
- [ ] Coverage: routing logic (correct queue per type)
- [ ] Coverage: confidence < 0.7 -> human review flag
- [ ] Coverage: "still happening" escalation rate limiting
- [ ] Coverage: feature request skips severity, goes to product backlog
- [ ] Coverage: timeout fallback to P3/bug
- [ ] Coverage: screenshot content exclusion from LLM context
- [ ] LLM calls mocked in Tier 1 (Kaizen mock provider)
      **Notes**: Tier 2 integration tests with real LLM covered in AI-040.

---

## HAR A2A Message Handler

### AI-040: Ed25519 key generation for registered agents

**Effort**: 3h
**Depends on**: agent_cards table (HAR data layer)
**Description**: Generate Ed25519 keypair for each agent upon registration. Private key stored securely; public key published in agent card.
**Acceptance criteria**:

- [ ] Ed25519 keypair generated using `cryptography` library (PyCA)
- [ ] Private key stored encrypted in database (or env-configured secret store in production)
- [ ] Public key stored in `agent_cards.public_key` column (PEM-encoded)
- [ ] Key generation happens during agent registration (`POST /api/v1/registry/agents`)
- [ ] Private key never returned in API responses
- [ ] Private key never logged
      **Notes**: Phase 1: HAR holds all private keys (signing proxy). Phase 2: BYOK (agents bring their own keys).

### AI-041: A2A message signing (HAR proxy)

**Effort**: 4h
**Depends on**: AI-040
**Description**: Implement message signing where HAR signs outbound A2A messages on behalf of the sending agent. Phase 1 simplification: agents do not need their own signing infrastructure.
**Acceptance criteria**:

- [ ] Sign outbound messages: Ed25519 signature over SHA-256(header || payload)
- [ ] Signature included in A2A message `signature` field
- [ ] Nonce (random 32 bytes hex) included in header to prevent replay
- [ ] Timestamp included in header; receiving side rejects messages > 5 minutes old
- [ ] Signing uses the agent's private key (looked up by from_agent_id)
- [ ] Signature is deterministic given same input (no randomness beyond nonce)
      **Notes**: Phase 1 is a signing proxy. HAR controls all keys. Phase 2 introduces BYOK.

### AI-042: A2A message signature verification

**Effort**: 3h
**Depends on**: AI-040, AI-041
**Description**: Verify Ed25519 signatures on inbound A2A messages using the sender's public key from the agent card.
**Acceptance criteria**:

- [ ] Look up sender's public key from `agent_cards.public_key` by `from_agent_id`
- [ ] Verify Ed25519 signature over SHA-256(header || payload)
- [ ] Reject message if signature invalid (return 401)
- [ ] Reject message if timestamp > 5 minutes old (replay protection)
- [ ] Reject message if nonce has been seen before within 10-minute window (replay protection via Redis set)
- [ ] Log verification result (success/failure) with message_id for audit
      **Notes**: Nonce deduplication uses Redis SET with TTL=600s (10 minutes).

### AI-043: Transaction state machine

**Effort**: 4h
**Depends on**: AI-041, AI-042
**Description**: Implement the transaction state machine for A2A transactions per Plan 07 Sprint 1-B.
**Acceptance criteria**:

- [ ] States: DRAFT -> OPEN -> NEGOTIATING -> COMMITTED -> EXECUTING -> COMPLETED; ABANDONED; DISPUTED -> RESOLVED
- [ ] Valid transitions enforced (invalid transition returns 400 with allowed transitions)
- [ ] Each state transition recorded in `har_transaction_events` table
- [ ] State stored in `har_transactions.current_state` column
- [ ] Transition triggers: inbound A2A message type maps to state transition
- [ ] ABANDONED: either party can abandon from DRAFT, OPEN, or NEGOTIATING
- [ ] DISPUTED: can only enter from COMMITTED, EXECUTING, or COMPLETED
- [ ] RESOLVED: can only enter from DISPUTED (requires human resolution)
      **Notes**: State machine must be strict. No skipping states (e.g., cannot go from OPEN directly to COMPLETED).

### AI-044: Signature chaining (tamper-evident audit)

**Effort**: 3h
**Depends on**: AI-043
**Description**: Implement signature chaining where each transaction event's platform signature covers the previous event's hash plus the current event data, creating a tamper-evident chain.
**Acceptance criteria**:

- [ ] Each `har_transaction_events` row includes `prev_event_hash` (SHA-256 of previous event in same txn)
- [ ] Platform signature covers: `SHA-256(prev_event_hash || event_type || payload_hash || timestamp)`
- [ ] First event in a transaction: `prev_event_hash` = SHA-256 of txn_id (genesis)
- [ ] Verification function: given a txn_id, verify entire chain from genesis to latest event
- [ ] Chain break detection: if any event is altered, all subsequent signatures become invalid
- [ ] `verify_chain(txn_id) -> (bool, Optional[int])` — returns (valid, first_broken_index)
      **Notes**: This is the Phase 1 alternative to blockchain. Centrally controlled by mingai but tamper-evident.

### AI-045: Human approval gate

**Effort**: 4h
**Depends on**: AI-043
**Description**: Implement human approval gates for transactions exceeding configurable thresholds.
**Acceptance criteria**:

- [ ] Per-tenant configurable threshold: default $5,000, max $1,000,000
- [ ] Threshold configurable per transaction type (e.g., RFQ: no approval; PO: $5,000+)
- [ ] When threshold exceeded: transaction pauses in COMMITTED state; approval request sent
- [ ] Approval request sent via email notification (tenant admin's email)
- [ ] In-app notification also created for tenant admin
- [ ] Timeout: 48 hours (configurable per tenant); expired approvals auto-reject
- [ ] Approval response: APPROVE or REJECT with optional reason
- [ ] Approval/rejection recorded in `har_transaction_events` as HUMAN_APPROVED / HUMAN_REJECTED event
- [ ] Financial transactions (Tier 3): human approval ALWAYS required (cannot be disabled)
      **Notes**: Per AD-03 in Plan 07: approval gates default to ON for Tier 2+.

---

## Trust Score Calculator

### AI-046: compute_trust_score function

**Effort**: 3h
**Depends on**: agent_cards table, har_transaction_events table
**Description**: Implement trust score calculation for registered agents per the formula in Plan 07 Sprint 2-B.
**Acceptance criteria**:

- [ ] `compute_trust_score(agent_id: str) -> int` returns score 0-100
- [ ] Components: base_attestation = kyb_level \* 25 (kyb_level 0-4)
- [ ] Components: txn_volume_score = min(log10(txn_count+1) / log10(1000), 1.0) \* 20
- [ ] Components: dispute_score = (1 - dispute_rate) \* 25
- [ ] Components: uptime_score = uptime_rate \* 15
- [ ] Components: response_score = response_time_score \* 10 (p99 response time vs SLA)
- [ ] Constraint: unverified (kyb_level=0) -> cap at 40
- [ ] Constraint: active dispute -> cap at 50
- [ ] Constraint: suspended agent -> return 0
- [ ] Score cached in `agent_cards.trust_score` column; recalculated on each transaction completion and daily batch job
      **Notes**: Phase 1 kyb_level is always 0 (no KYB in Phase 0-1). Trust score will be low until Phase 2 adds KYB.

### AI-047: Trust score unit tests

**Effort**: 2h
**Depends on**: AI-046
**Description**: Unit tests for trust score calculation.
**Acceptance criteria**:

- [ ] Test: new agent (0 transactions, no KYB) -> score <= 40
- [ ] Test: 1000 transactions, no disputes, high uptime -> score near maximum for kyb_level
- [ ] Test: unverified cap (score never exceeds 40 without KYB)
- [ ] Test: active dispute cap (score never exceeds 50)
- [ ] Test: suspended agent -> always 0
- [ ] Test: dispute rate impact (0% vs 5% vs 20%)
- [ ] Test: response time scoring (fast vs slow vs SLA breach)
- [ ] Test: edge case: agent with 0 transactions (log10(1) = 0)

---

## Health Monitor

### AI-048: Agent health monitor background job

**Effort**: 3h
**Depends on**: agent_cards table
**Description**: Background job that pings the `health_check_url` for each registered agent at regular intervals and marks unhealthy agents as UNAVAILABLE.
**Acceptance criteria**:

- [ ] Runs every 5 minutes (configurable via env `HEALTH_CHECK_INTERVAL_SECONDS`, default 300)
- [ ] Pings `health_check_url` for each active agent with status != "suspended"
- [ ] Healthy response: HTTP 200 within 10 seconds
- [ ] Tracks consecutive failure count per agent in Redis: `har:health:{agent_id}:failures`
- [ ] 3 consecutive failures -> mark agent status = "unavailable" in `agent_cards` table
- [ ] Recovery: successful ping after unavailable -> reset failure count, mark agent "active" again
- [ ] Health check results logged for observability (agent_id, status, response_time_ms)
- [ ] Does not block if one agent is slow (asyncio.gather with per-agent timeout)
      **Notes**: Must handle large numbers of agents efficiently. Use asyncio for concurrent health checks.

### AI-049: Health monitor unit tests

**Effort**: 2h
**Depends on**: AI-048
**Description**: Unit tests for the health monitor job.
**Acceptance criteria**:

- [ ] Test: healthy agent stays active
- [ ] Test: 1-2 failures, agent stays active (not yet threshold)
- [ ] Test: 3 consecutive failures -> agent marked unavailable
- [ ] Test: recovery after unavailable (successful ping resets)
- [ ] Test: suspended agents skipped (not pinged)
- [ ] Test: slow endpoint times out (does not block other checks)
- [ ] Test: concurrent health checks for multiple agents

---

## Cross-Cutting Integration Tests

### AI-050: Profile + memory full pipeline integration test

**Effort**: 4h
**Depends on**: AI-032, AI-035, AI-036
**Description**: End-to-end integration test validating the complete profile and memory pipeline from query to personalized system prompt.
**Acceptance criteria**:

- [ ] Test: user with full profile (all layers populated) -> system prompt contains all layers
- [ ] Test: user with no profile (first-time user) -> system prompt has only Layer 0 + Layer 1
- [ ] Test: 10th query triggers profile learning -> profile updated -> next prompt reflects new profile
- [ ] Test: "remember that" creates note -> note appears in Layer 3 on next query
- [ ] Test: GDPR clear_profile_data -> all layers empty on next query (including working memory)
- [ ] Test: tenant with profile_learning_enabled=false -> no profile learning triggered
- [ ] Test: team member -> Layer 4b populated; solo user -> Layer 4b absent
- [ ] Uses real PostgreSQL, real Redis; LLM extraction mocked
      **Notes**: This is the most important integration test. Validates the entire memory stack end-to-end.

### AI-051: HAR A2A full transaction integration test

**Effort**: 4h
**Depends on**: AI-041, AI-042, AI-043, AI-044, AI-045
**Description**: End-to-end integration test for a complete A2A transaction lifecycle.
**Acceptance criteria**:

- [ ] Test: full RFQ -> QUOTE -> PO -> DELIVERY -> COMPLETED flow with signature verification at each step
- [ ] Test: signature chain verification passes for completed transaction
- [ ] Test: human approval gate fires at threshold, blocks until approved
- [ ] Test: approval timeout (48h) -> auto-reject
- [ ] Test: invalid signature -> message rejected with 401
- [ ] Test: replay attack (reused nonce) -> rejected
- [ ] Test: state machine violation (skip state) -> rejected with 400
- [ ] Uses real PostgreSQL and real Redis
      **Notes**: No real A2A endpoints needed. Tests use loopback (same instance acting as both buyer and seller).

---

## Summary

| Section                     | Todos            | Total Effort |
| --------------------------- | ---------------- | ------------ |
| Profile Learning Service    | AI-001 to AI-008 | 24.5h        |
| Working Memory Service      | AI-009 to AI-012 | 9.5h         |
| Team Working Memory Service | AI-013 to AI-015 | 14h          |
| Org Context Service         | AI-016 to AI-022 | 18h          |
| Memory Notes Service        | AI-023 to AI-025 | 10h          |
| Glossary Expander           | AI-026 to AI-031 | 21h          |
| System Prompt Builder       | AI-032 to AI-036 | 22h          |
| Issue Triage Agent          | AI-037 to AI-039 | 13h          |
| HAR A2A Message Handler     | AI-040 to AI-045 | 21h          |
| Trust Score Calculator      | AI-046 to AI-047 | 5h           |
| Health Monitor              | AI-048 to AI-049 | 5h           |
| Cross-Cutting Integration   | AI-050 to AI-051 | 8h           |
| Gap Remediation             | AI-052 to AI-060 | 72h          |
| **Total**                   | **60 todos**     | **~243h**    |

---

## Gap Remediation (from 07-gap-analysis.md)

### AI-052: AML/sanctions screening for HAR Tier 3

**Effort**: 16h
**Depends on**: AI-041
**Description**: AML/sanctions screening service for HAR Tier 3 financial transaction parties. Integrates with a third-party compliance API (Dow Jones, Refinitiv, or ComplyAdvantage) to screen buyer and seller entities against OFAC, EU, and UN sanctions lists before any Tier 3 transaction is executed. Phase 2 gate — must not ship without this for any transaction involving financial commitment.
**Acceptance criteria**:

- [ ] Screen both parties (buyer + seller agent owners) against OFAC, EU, UN sanctions lists
- [ ] Third-party compliance API integration with configurable provider
- [ ] Screening result cached per entity for 24h (re-screen on new transaction if cache expired)
- [ ] Transaction blocked with `COMPLIANCE_HOLD` status if match found
- [ ] Platform admin notified of compliance holds for manual review
- [ ] Suspicious Activity Report (SAR) template generated for flagged transactions
- [ ] Screening audit trail stored (who was screened, when, result, provider)
- [ ] All API keys read from env/secrets manager (never hardcoded)
      **Notes**: GAP-004. CRITICAL. Phase 2 gate — do not deploy HAR Tier 3 without this. Regulatory obligation for any platform facilitating financial transactions.

### AI-053: RetrievalConfidenceCalculator service

**Effort**: 4h
**Depends on**: none
**Description**: Service that calculates the retrieval confidence score from vector search results. This is the numeric value displayed in the chat UI as "retrieval confidence" and included in SSE metadata. Algorithm: `mean(top_3_scores) * 0.6 + min(result_count / 5, 1.0) * 0.2 + recency_factor * 0.2`. Label strictly as "retrieval quality proxy" — never "answer quality."
**Acceptance criteria**:

- [ ] Input: list of vector search results with similarity scores and timestamps
- [ ] Output: float 0.0-1.0
- [ ] Algorithm: `mean(top_3_scores) * 0.6 + min(result_count / 5, 1.0) * 0.2 + recency_factor * 0.2`
- [ ] Recency factor: 1.0 if newest result < 7 days, decays linearly to 0.5 at 90 days
- [ ] Returns 0.0 for empty result set
- [ ] Returns score for partial results (fewer than 3 — use available scores)
- [ ] Score included in SSE `metadata` event as `retrieval_confidence`
      **Notes**: GAP-015. HIGH. Frontend already expects this value but no service produces it.

### AI-054: EmbeddingService

**Effort**: 6h
**Depends on**: none
**Description**: Foundation service for generating text embeddings. Wraps the configured embedding model (read from tenant config) with rate limiting, float16 compression for cache storage, and batch support. Used by chat pipeline (step 3), document indexing, and semantic cache.
**Acceptance criteria**:

- [ ] `embed_query(text, tenant_id)` returns embedding vector
- [ ] `embed_batch(texts, tenant_id)` returns list of embedding vectors
- [ ] Model name read from tenant config (never hardcoded)
- [ ] Float16 compression for cache storage (halves memory)
- [ ] Rate limit handling with exponential backoff on 429 from provider
- [ ] Tenant-scoped usage tracking (tokens consumed per call)
- [ ] Handles empty text input (returns zero vector or raises ValueError)
- [ ] Cloud-provider abstraction: Azure OpenAI, OpenAI, Vertex AI embedding endpoints
      **Notes**: GAP-017. HIGH. Foundation service — chat, caching, and document indexing all depend on this.

### AI-055: VectorSearchService

**Effort**: 8h
**Depends on**: AI-054
**Description**: Cloud-provider abstraction layer for vector search. Strategy pattern selects backend based on `CLOUD_PROVIDER` env var: OpenSearch (AWS), Azure AI Search (Azure), Vertex AI Search (GCP). Supports parallel multi-index search, tenant-scoped indexes, and result deduplication.
**Acceptance criteria**:

- [ ] Strategy pattern: `OpenSearchBackend`, `AzureAISearchBackend`, `VertexAISearchBackend`
- [ ] Backend selected by `CLOUD_PROVIDER` env var
- [ ] `search(query_embedding, tenant_id, index_ids, top_k)` returns ranked results
- [ ] Parallel multi-index search (asyncio.gather across indexes)
- [ ] Tenant-scoped index naming: `mingai-{tenant_id}-{index_name}`
- [ ] Result deduplication by document chunk ID across indexes
- [ ] Results include: chunk_text, similarity_score, document_id, metadata
- [ ] Handles index not found gracefully (skip, log warning)
- [ ] Connection pooling per backend
      **Notes**: GAP-018. HIGH. Foundation service — RAG pipeline step 4.

### AI-056: ChatOrchestrationService (RAG pipeline orchestrator)

**Effort**: 16h
**Depends on**: AI-053, AI-054, AI-055, AI-032
**Description**: The central orchestrator that ties the entire RAG pipeline together. Implements the 8-step pipeline: (0) glossary pre-translation, (1) JWT validation (already done by middleware — extract context), (2) intent detection, (3) embedding generation, (4) parallel vector search, (5) SystemPromptBuilder, (6) LLM streaming synthesis, (7) confidence scoring, (8) SSE event emission + conversation persistence. This is the most critical missing service — API-007 (POST /chat/stream) calls this.
**Acceptance criteria**:

- [ ] 8-step pipeline executed in correct order with proper data flow between steps
- [ ] Step 0: glossary pre-translation applied to query if tenant flag enabled
- [ ] Step 2: intent detection classifies query (rag_query, greeting, clarification, remember, feedback)
- [ ] Step 2 fast path: "remember that" intent skips steps 3-7, creates memory note directly
- [ ] Step 3: embedding generated via EmbeddingService
- [ ] Step 4: parallel vector search across tenant's indexes
- [ ] Step 5: SystemPromptBuilder assembles all layers
- [ ] Step 6: LLM streaming with SSE chunk emission
- [ ] Step 7: confidence scoring via RetrievalConfidenceCalculator
- [ ] Step 8: conversation and message persisted after stream completes
- [ ] SSE events emitted in order: status, sources, response_chunk (multiple), metadata, done
- [ ] Pipeline aborts gracefully on LLM provider error (emits error SSE event)
- [ ] Pipeline timeout: 30s max (configurable per tenant)
- [ ] All LLM model names from tenant config (never hardcoded)
- [ ] Observability: pipeline stage timings emitted as metrics
      **Notes**: GAP-019. CRITICAL. This is the MOST CRITICAL gap — the platform's core functionality depends on this service. All other AI services feed into or are called by this orchestrator.

### AI-059: ConversationPersistenceService

**Effort**: 6h
**Depends on**: none
**Description**: Service that handles the write side of conversation management: creating conversation records, persisting messages (both user and AI), storing metadata (tokens used, model, confidence), and managing conversation lifecycle. API-006/008 read conversations; this service writes them.
**Acceptance criteria**:

- [ ] `create_conversation(tenant_id, user_id, agent_id, title)` creates conversation record
- [ ] `append_message(conversation_id, role, content, metadata)` persists a message
- [ ] AI response persisted AFTER stream completes (not during streaming)
- [ ] Message metadata includes: token_count, model_used, retrieval_confidence, response_time_ms
- [ ] Title auto-generation: first user message summarized to <50 chars by LLM (async, non-blocking)
- [ ] Conversation closed after 30 minutes of inactivity (background job)
- [ ] Tenant-scoped (all queries filter by tenant_id)
- [ ] Handles concurrent messages to same conversation (ordering by timestamp)
      **Notes**: GAP-054. HIGH. Without this, chat responses are generated but never saved.

### AI-060: DocumentIndexingPipeline

**Effort**: 10h
**Depends on**: AI-054, AI-055
**Description**: Pipeline that transforms synced documents into searchable vector index entries. Steps: parse document (PDF/DOCX/PPTX/TXT) -> chunk (512 tokens, 50 token overlap) -> embed each chunk -> upsert to vector search index with tenant metadata. Handles incremental updates (re-index only changed documents).
**Acceptance criteria**:

- [ ] Parse: PDF (PyPDF2/pdfplumber), DOCX (python-docx), PPTX (python-pptx), TXT
- [ ] Chunking: 512-token chunks with 50-token overlap (sliding window)
- [ ] Embedding: each chunk embedded via EmbeddingService (batch mode)
- [ ] Upsert: chunks upserted to tenant-scoped vector index
- [ ] Metadata per chunk: document_id, chunk_index, source_path, last_modified, tenant_id
- [ ] Incremental: only re-index documents where last_modified > last_indexed_at
- [ ] Delete: remove chunks for deleted documents
- [ ] Progress tracking: emit progress events for long-running indexing jobs
- [ ] Error handling: skip unparseable documents, log error, continue with remaining
- [ ] Rate limiting: respect embedding API rate limits during batch indexing
      **Notes**: GAP-055. HIGH. INFRA-025 syncs files but this pipeline makes them searchable. Without it, RAG returns no results.
