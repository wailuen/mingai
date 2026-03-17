# LLM Credentials Codebase Analysis

**Date**: 2026-03-17
**Source**: Automated codebase explorer — 15 source files across `app/core` and `app/modules`
**Purpose**: Complete inventory of all `.env` LLM dependencies to scope the DB migration

---

## Environment Variable Inventory

| Env Var                             | Files    | Count | What Configures                             |
| ----------------------------------- | -------- | ----- | ------------------------------------------- |
| `AZURE_PLATFORM_OPENAI_API_KEY`     | 7 files  | 7     | Platform default LLM API key                |
| `AZURE_PLATFORM_OPENAI_ENDPOINT`    | 7 files  | 7     | Platform default LLM endpoint               |
| `AZURE_PLATFORM_OPENAI_API_VERSION` | 2 files  | 2     | Azure SDK API version (default: 2024-02-01) |
| `PRIMARY_MODEL`                     | 10 files | 10    | Chat completions & agent responses          |
| `INTENT_MODEL`                      | 4 files  | 4     | Intent detection & routing                  |
| `EMBEDDING_MODEL`                   | 3 files  | 3     | Document embeddings & semantic search       |
| `OPENAI_API_KEY`                    | 2 files  | 2     | BYOLLM mode OpenAI Direct provider          |
| `BYOLLM_COST_PER_1K_IN_USD`         | 1 file   | 1     | Usage cost calculation fallback             |
| `BYOLLM_COST_PER_1K_OUT_USD`        | 1 file   | 1     | Usage cost calculation fallback             |
| `CLOUD_PROVIDER`                    | 4 files  | 4     | Provider type selector                      |
| `ROUTER_MODEL`                      | 1 file   | 1     | Intent detection fallback (legacy)          |

---

## Critical Finding: `InstrumentedLLMClient` Is NOT the Only Entry Point

Multiple modules **bypass** `InstrumentedLLMClient` and instantiate LLM clients directly from env vars. Every one of these must be migrated.

### Modules That Bypass InstrumentedLLMClient

| Module                                                | File                                                   | Env Vars Read                                         | Fix Required                             |
| ----------------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------------- | ---------------------------------------- |
| `ChatOrchestrator._generate_answer()`                 | `app/modules/chat/orchestrator.py:627,639-640`         | PRIMARY*MODEL, AZURE_PLATFORM_OPENAI*\*               | Route through InstrumentedLLMClient      |
| `IntentDetectionService._get_llm_client()`            | `app/modules/chat/intent_detection.py:299-301,354-366` | INTENT*MODEL, ROUTER_MODEL, CLOUD_PROVIDER, AZURE*\*  | Route through shared provider resolution |
| `EmbeddingService.__init__()`                         | `app/modules/chat/embedding.py:52-66`                  | EMBEDDING*MODEL, CLOUD_PROVIDER, AZURE*\*             | Read from DB profile                     |
| `TriageAgent._call_llm()`                             | `app/modules/issues/triage_agent.py:159,173-174,193`   | INTENT*MODEL, PRIMARY_MODEL, AZURE*\*, OPENAI_API_KEY | Route through InstrumentedLLMClient      |
| `ProfileLearningService._run_intent_classification()` | `app/modules/profile/learning.py:400,448-449,464`      | INTENT*MODEL, PRIMARY_MODEL, AZURE*\*, OPENAI_API_KEY | Route through InstrumentedLLMClient      |
| `AgentExecutor._run_agent_test()`                     | `app/modules/agents/routes.py:1846,1858-1859`          | PRIMARY*MODEL, AZURE_PLATFORM_OPENAI*\*               | Route through InstrumentedLLMClient      |
| LLM Library test harness                              | `app/modules/platform/llm_library/routes.py:535`       | (via AzureOpenAIProvider())                           | Pass credentials from DB                 |
| Platform template test                                | `app/modules/platform/routes.py:1172,1255`             | PRIMARY_MODEL, (via AzureOpenAIProvider())            | Pass credentials from DB                 |

### `InstrumentedLLMClient` Direct Env Reads

| Location                         | Env Var                             | Purpose                   |
| -------------------------------- | ----------------------------------- | ------------------------- |
| `instrumented_client.py:107`     | `EMBEDDING_MODEL`                   | Embedding model name      |
| `instrumented_client.py:152`     | `PRIMARY_MODEL`                     | Library mode chat model   |
| `instrumented_client.py:211`     | `PRIMARY_MODEL`                     | BYOLLM fallback model     |
| `instrumented_client.py:220-221` | `AZURE_PLATFORM_OPENAI_API_VERSION` | BYOLLM Azure API version  |
| `instrumented_client.py:359-360` | `BYOLLM_COST_PER_1K_IN/OUT_USD`     | Cost calculation fallback |

### `AzureOpenAIProvider` Constructor

**File**: `app/core/azure_openai.py` (note: different from `app/core/llm/azure_openai.py`)

```python
# Current: reads from env in __init__
def __init__(self) -> None:
    self._client = _get_azure_client()  # reads AZURE_PLATFORM_OPENAI_* internally

# Target: accepts credentials as parameters
def __init__(self, api_key: str, endpoint: str, api_version: str = "2024-02-01") -> None:
    from openai import AsyncAzureOpenAI
    self._client = AsyncAzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)
```

4 instantiation sites must be updated to pass credentials.

---

## Env Vars That Can Be Removed After Migration

| Env Var                             | Replacement in DB                                        |
| ----------------------------------- | -------------------------------------------------------- |
| `AZURE_PLATFORM_OPENAI_API_KEY`     | `llm_providers.api_key_encrypted` (Fernet)               |
| `AZURE_PLATFORM_OPENAI_ENDPOINT`    | `llm_providers.endpoint`                                 |
| `AZURE_PLATFORM_OPENAI_API_VERSION` | `llm_providers.options.api_version`                      |
| `PRIMARY_MODEL`                     | `llm_providers.models.primary`                           |
| `INTENT_MODEL`                      | `llm_providers.models.intent`                            |
| `EMBEDDING_MODEL`                   | `llm_providers.models.doc_embedding`                     |
| `BYOLLM_COST_PER_1K_IN_USD`         | `llm_library.pricing_per_1k_tokens_in` (already exists)  |
| `BYOLLM_COST_PER_1K_OUT_USD`        | `llm_library.pricing_per_1k_tokens_out` (already exists) |
| `ROUTER_MODEL`                      | deprecated — INTENT_MODEL replaces                       |

**Keep in `.env`** (infrastructure, not LLM):

- `CLOUD_PROVIDER` — System-level (determines infra adapters)
- `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY` — Infrastructure
- `AUTH0_*` — Auth

---

## Bootstrap Auto-Seed (Already Partially Exists)

`app/core/bootstrap.py` lines 196-199 already seeds initial `llm_profiles` from env vars:

```python
"primary_model": os.environ.get("PRIMARY_MODEL", "agentic-worker"),
"intent_model": os.environ.get("INTENT_MODEL", "agentic-router"),
"embedding_model": os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
"endpoint_url": os.environ.get("AZURE_OPENAI_ENDPOINT", "https://..."),
```

This is the bootstrap mechanism to use — extend it to also store `api_key_encrypted` so the DB row is fully populated from env on first boot, then UI takes over.

---

## Required Code Changes Summary

### Tier 1: Provider Constructor Fix

- `app/core/azure_openai.py` — change `__init__()` to accept `(api_key, endpoint, api_version)` params

### Tier 2: InstrumentedLLMClient Migration

- `app/core/llm/instrumented_client.py` — `_resolve_library_adapter()` and `embed()` read from `ProviderService` DB lookup

### Tier 3: Bypass Module Migration (8 modules)

All 8 modules that bypass `InstrumentedLLMClient` must be updated. Two patterns:

1. **Stateless operations** (TriageAgent, LearningService, AgentExecutor) → route through `InstrumentedLLMClient.complete()`
2. **Service init** (EmbeddingService, IntentDetectionService) → inject provider at construction from `ProviderService`

### Tier 4: Env Fallback Removal

- `app/core/tenant_config_service.py:144` — remove Tier 3 env fallback
- `app/core/config.py` — deprecate LLM-related Settings fields
