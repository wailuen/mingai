# 36 — Profile & Memory Architecture (aihub2 Reference)

**Source**: `/Users/wailuen/Development/aihub2`
**Scope**: Full technical audit of user profiling, working memory, memory notes, and org context systems.
**Status**: Complete reference for mingai adaptation.

---

## 1. Overview: The 4-Layer Memory Stack

aihub2 implements a four-layer memory model that operates inside the system prompt at query time:

```
Layer 2: Org Context           (500 tokens)  — Who the user IS (org identity)
Layer 3: Profile Context       (200 tokens)  — What the user PREFERS (learned profile + top 5 memory notes)
Layer 4: Working Memory        (100 tokens)  — What the user is WORKING ON (recent topics + last 3 queries)
Layer 6: Glossary Context      (500 tokens)  — Tenant-scoped terminology
```

All four layers are injected into `SystemPromptBuilder` and assembled in a single `asyncio.gather()` call to minimize latency.

**mingai canonical token budget (supersedes aihub2 values above)**:

- Org Context: 500 → **100 tokens** (right-sized; actual usage is ~70 tokens, 30-token buffer added)
- Glossary: 500 → **0 tokens** in system prompt (replaced by inline query pre-translation — see doc 37-glossary-pretranslation-architecture.md)
- Team Working Memory: **150 tokens** added as Layer 4b (new in mingai — see doc 39-teams-collaboration-architecture.md)
- Total memory overhead: **550 tokens** (down from ~1,300 in aihub2)
- RAG at 2K budget: **1,450 tokens** (up from ~700 in aihub2)

---

## 2. Profile Learning Service

**File**: `app/modules/users/profile_learning.py` (775+ lines)

### 2.1 Trigger Mechanism

- **Frequency**: Every 10 user queries (counted in Redis, key: `profile_learning:query_count:{user_id}`)
- **Execution**: Async, fire-and-forget — never blocks the query response
- **Scope**: Last 10 conversations analyzed per learning cycle

### 2.2 LLM Extraction

**Model**: GPT-4.1-mini (cost-efficient intent model, same as intent detection)

**Extracted attributes**:
| Field | Type | Limit | Notes |
|-------|------|-------|-------|
| `interests` | `string[]` | 20 items | Topics user frequently asks about |
| `expertise_areas` | `string[]` | 10 items | Domains with demonstrated knowledge |
| `technical_level` | `enum` | — | `beginner` / `intermediate` / `expert` |
| `communication_style` | `enum` | — | `concise` / `detailed` / `formal` / `casual` |
| `common_tasks` | `string[]` | 15 items | Recurring work patterns |
| `memory_notes` | `string[]` | 5 per extraction | Auto-extracted facts from conversation |

### 2.3 Merge Strategy

Profile updates are additive, not destructive:

- Arrays: union of existing + new, capped at limits
- `technical_level`: weighted average with recency bias
- `communication_style`: most recent wins

### 2.4 Caching

Two-tier cache:

- **L1**: In-memory LRU (200 entries, 30-min TTL, `ProfileLRUCache` class)
- **L2**: Redis (1-hour TTL, key: `profile_learning:profile:{user_id}`)
- **L3**: CosmosDB (persistent ground truth, `user_profiles` container)

### 2.5 GDPR Compliance

- `clear_profile_data()`: wipes all attributes + memory notes + audit trail from Cosmos + Redis + L1
- `export_profile_data()`: returns full profile as JSON including memory notes
- Audit trail: `learning_events` array stored in `user_profiles` document

---

## 3. Working Memory Service

**File**: `app/modules/users/working_memory.py` (~256 lines)

### 3.1 Architecture

Redis-only, no Cosmos persistence:

- **Key**: `{prefix}working_memory:{user_id}`
- **TTL**: 7 days (auto-expires, no manual cleanup needed)
- **LLM cost**: $0 — uses simple keyword extraction (stop-word filter)

### 3.2 Data Structure

```json
{
  "topics": ["AWS bonus", "CPF", "leave policy"],
  "recent_queries": [
    "How do I calculate AWS?",
    "What is the AWS bonus deadline?",
    "Can I defer my AWS?"
  ],
  "last_conversation_id": "conv_123",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

- **Max topics**: 5 (new topics prepended, oldest pruned)
- **Max queries**: 3 (newest first, deduplication)
- **Query truncation**: 100 chars

### 3.3 Returning User Detection

If `updated_at` gap > 1 hour:

- Shows "Returning user from earlier session" in prompt
- Shows last 2 queries instead of 1

### 3.4 Topic Extraction

Regex: words ≥3 chars, filtered against 80+ stop words. No NLP, no LLM. Max 3 topics extracted per query.

### 3.5 Update Hook

Called in `ProfileLearningService.on_query_completed()` after every query. Fire-and-forget, exception-safe.

---

## 4. Memory Notes

**TODO-70 completion date**: 2026-02-26

### 4.1 Two Sources

| Source             | Trigger                                            | Confirmation                                     |
| ------------------ | -------------------------------------------------- | ------------------------------------------------ |
| **User-directed**  | User types "remember that X" / "please remember X" | Immediate SSE `memory_saved` event (no LLM call) |
| **Auto-extracted** | Part of profile learning cycle (every 10 queries)  | Silent, stored in background                     |

### 4.2 Data Model

```python
class MemoryNote(BaseModel):
    id: str                     # UUID
    content: str                # The fact text
    created_at: datetime        # Timestamp
    source: str                 # "user_directed" | "auto_extracted"
```

### 4.3 Limits

- **Max**: 15 notes total per user
- **Oldest pruned** when limit exceeded
- **Top 5** injected into system prompt (newest first)

### 4.4 API Endpoints

```
GET    /users/me/memory              → all notes (newest first)
DELETE /users/me/memory/{note_id}    → delete one note
DELETE /users/me/memory             → clear all notes (GDPR)
```

### 4.5 Intent Detection in Chat Router

Before the LLM pipeline, a regex pattern check on the message:

- Pattern: `r'\b(remember|note|save|store|keep)\s+(that|this)?\b'`
- Match: extract fact, call `add_memory_note()`, return SSE confirmation immediately
- No LLM invoked — pure fast path

### 4.6 Prompt Integration

Memory notes injected in **Layer 3** (Profile Context), token limit raised 100→200:

- Template: `"Memory notes (things to always remember):\n- {note1}\n- {note2}..."`
- Only newest 5 notes included

### 4.7 UI Components

- `MemoryNotesList.tsx`: list with timestamps, source badge ("saved by you" vs "auto-extracted"), delete button
- `useUserMemory.ts`: hooks for CRUD operations
- Settings > Privacy page: Memory card section
- Toast: "Memory saved" badge in chat when note stored

---

## 5. Org Context Layer

**TODO-05A completion date**: 2025-12-23

### 5.1 Data Source

Azure AD user attributes synced at login (no MSGraph calls at query time):

- `job_title`
- `department`
- `country`
- `company`
- `manager_name` / `manager_email` (privacy-controlled)

### 5.2 LLM Interpretation Strategy

Raw org data injected into prompt with instruction to interpret contextually. No hardcoded mappings.

**Why**: LLM handles "Senior Financial Analyst" → finance focus, "Singapore" → IRAS/CPF context, without any static rules.

### 5.3 Privacy Controls

| Toggle                | Default | Effect                            |
| --------------------- | ------- | --------------------------------- |
| `org_context_enabled` | ON      | Master toggle for all org context |
| `share_manager_info`  | ON      | Include/exclude manager name      |

Both stored in `UserPreferences` schema, applied at query-build time.

### 5.4 Token Budget

aihub2 allocated 500 tokens for Layer 2 (org context + instructional text). Actual usage is ~70 tokens. **mingai canonical budget: 100 tokens** (right-sized with 30-token buffer — see Section 1 note).

### 5.5 Known Limitations

- **Local auth users**: No org data → layer silently skipped
- **Data staleness**: Only refreshed on login
- **Read-only**: User cannot edit org data

---

## 6. System Prompt Assembly

Full stack built in `app/modules/chat/service.py`, `_build_system_prompt_with_context()`:

```python
user_doc, profile_context, glossary_terms, working_memory_context = await asyncio.gather(
    self._get_user_document(user_id),
    self._get_profile_context(user_id),
    self._get_glossary_terms_for_prompt(...),
    self._get_working_memory_context(user_id),
    return_exceptions=True
)

builder = SystemPromptBuilder()
result = (
    builder
    .add_base_layer()
    .add_org_context_layer(org_context)           # Layer 2: 500 tokens (aihub2) → 100 tokens (mingai canonical)
    .add_profile_layer(profile_context)            # Layer 3: 200 tokens
    .add_working_memory_layer(working_memory_context)  # Layer 4: 100 tokens
    .add_domain_layer(custom_prompt, is_rag_mode)  # Layer 5: no limit
    .add_glossary_layer(glossary_terms)            # Layer 6: 500 tokens (aihub2) → REMOVED in mingai (pre-translation)
    .build()
)
```

All four context fetches run in parallel. Exceptions are caught and degraded gracefully.

---

## 7. Token Budget Summary

### aihub2 (reference only — do not use for mingai implementation)

| Layer              | Limit             | Content                                                    |
| ------------------ | ----------------- | ---------------------------------------------------------- |
| Org Context        | 500 tokens        | Job title + dept + country + instructions                  |
| Profile Context    | 200 tokens        | technical_level + style + interests + memory notes (top 5) |
| Working Memory     | 100 tokens        | Recent topics + last queries                               |
| Glossary           | 500 tokens        | Tenant-defined terms                                       |
| **Total overhead** | **~1,300 tokens** | Before domain/RAG context                                  |

At 2K token/query budget in aihub2, this leaves ~700 tokens for domain/RAG context.

### mingai Canonical Budget (use this for all implementation)

| Layer                          | Limit          | Content                                                    |
| ------------------------------ | -------------- | ---------------------------------------------------------- |
| Org Context                    | **100 tokens** | Job title + dept + country + instructions (right-sized)    |
| Profile Context                | 200 tokens     | technical_level + style + interests + memory notes (top 5) |
| Individual Working Memory      | 100 tokens     | Recent topics + last queries                               |
| Team Working Memory (Layer 4b) | **150 tokens** | Shared team topics + recent team queries (new in mingai)   |
| Glossary                       | **0 tokens**   | Pre-translated inline in query — not in system prompt      |
| **Total overhead**             | **550 tokens** | Before domain/RAG context                                  |

At 2K token/query budget (Professional tier): **1,450 tokens** for domain/RAG context.
At 4K token/query budget (Enterprise tier): **3,450 tokens** for domain/RAG context.

See doc 37-glossary-pretranslation-architecture.md for glossary pre-translation design.
See doc 39-teams-collaboration-architecture.md for Team Working Memory (Layer 4b) design.

---

## 8. Test Coverage (aihub2)

| Component                       | Tests              | Status    |
| ------------------------------- | ------------------ | --------- |
| ProfileLearningService          | 32 unit tests      | 100% pass |
| SystemPromptBuilder integration | 25 tests           | 100% pass |
| WorkingMemoryService            | 57 unit tests      | 100% pass |
| Working memory integration      | 15 tests           | 100% pass |
| Memory notes endpoints          | 4 unit tests       | 100% pass |
| Memory notes intent detection   | 3 unit tests       | 100% pass |
| Org context builder             | 12 unit tests      | 100% pass |
| Org context E2E                 | 2 Playwright specs | 100% pass |

---

## 9. Key Design Decisions (Carry Forward to mingai)

1. **LRU L1 cache** for profiles: avoids Redis round-trip on hot paths
2. **Fire-and-forget learning**: profile updates never block query response
3. **LLM interpretation of org data**: avoids static mappings, language-agnostic
4. **Redis-only for working memory**: zero marginal cost, auto-expiry, no migration risk
5. **Fast-path memory intent**: no LLM call for "remember that" commands
6. **Opt-out default** for profile learning: maximizes adoption, clear consent flow
7. **15-note cap** with oldest pruning: prevents unbounded growth
