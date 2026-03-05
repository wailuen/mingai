# LLM Model Slot Analysis

## 1. Current State: 6 Deployment Slots

The mingai backend defines six distinct Azure OpenAI deployment slots, each configurable with its own endpoint, API key, and deployment name. This separation allows independent scaling, region routing, and model selection per operational concern.

### Deployment Slot Inventory

| Slot                 | Env Var (Deployment)                    | Default Value            | Env Var (Endpoint)                    | Env Var (Key)                    | Current Model          |
| -------------------- | --------------------------------------- | ------------------------ | ------------------------------------- | -------------------------------- | ---------------------- |
| **Primary**          | `AZURE_OPENAI_PRIMARY_DEPLOYMENT`       | `mingai-main`            | `AZURE_OPENAI_ENDPOINT`               | `AZURE_OPENAI_KEY`               | GPT-5.2-chat           |
| **Auxiliary**        | `AZURE_OPENAI_AUXILIARY_DEPLOYMENT`     | `intent5`                | (shares primary)                      | (shares primary)                 | GPT-5 Mini             |
| **Intent Detection** | `AZURE_OPENAI_INTENT_DEPLOYMENT`        | `intent5`                | `AZURE_OPENAI_INTENT_ENDPOINT`        | `AZURE_OPENAI_INTENT_API_KEY`    | GPT-5 Mini             |
| **Vision**           | `AZURE_OPENAI_VISION_DEPLOYMENT`        | `gpt-vision`             | `AZURE_OPENAI_VISION_ENDPOINT`        | `AZURE_OPENAI_VISION_KEY`        | GPT-5 Vision           |
| **Doc Embedding**    | `AZURE_OPENAI_DOC_EMBEDDING_DEPLOYMENT` | `text-embedding-3-large` | `AZURE_OPENAI_DOC_EMBEDDING_ENDPOINT` | `AZURE_OPENAI_DOC_EMBEDDING_KEY` | text-embedding-3-large |
| **KB Embedding**     | `AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT`  | `text-embedding-ada-002` | `AZURE_OPENAI_KB_ENDPOINT`            | `AZURE_OPENAI_KB_KEY`            | text-embedding-ada-002 |

### Reasoning Effort Parameters

Two slots support configurable `reasoning_effort` (GPT-5 o-series parameter):

| Parameter        | Env Var                                | Default | Applied To                                                                       |
| ---------------- | -------------------------------------- | ------- | -------------------------------------------------------------------------------- |
| Intent reasoning | `AZURE_OPENAI_INTENT_REASONING_EFFORT` | `none`  | Intent detection, confidence scoring, auto-titling, suggestions, index selection |
| Chat reasoning   | `AZURE_OPENAI_CHAT_REASONING_EFFORT`   | `none`  | Chat synthesis, streaming responses                                              |

### Fallback Deployments

| Parameter       | Env Var                                   | Default            | Purpose                                   |
| --------------- | ----------------------------------------- | ------------------ | ----------------------------------------- |
| Intent fallback | `AZURE_OPENAI_INTENT_FALLBACK_DEPLOYMENT` | `intent-detection` | Fallback when intent endpoint unavailable |
| Chat fallback   | `AZURE_OPENAI_CHAT_FALLBACK_DEPLOYMENT`   | `mingai-main`      | Fallback when primary GPT-5 unavailable   |

### Key Design Decisions

- Each slot supports **optional separate endpoint and key**, falling back to the primary endpoint if not configured. This enables independent scaling per concern.
- Intent detection has a **fully separate Azure OpenAI resource** (`AZURE_OPENAI_INTENT_ENDPOINT`), allowing it to scale independently from chat synthesis on a different Azure region.
- Vision has **optional separate credentials**, enabling deployment on a specialized multimodal resource.
- The two embedding slots target different embedding models for different eras of indexed content (legacy ada-002 for existing KB indexes, embedding-3-large for new document uploads).

---

## 2. Model Registry Implementation

### Singleton Pattern

The `ModelRegistry` class (`app/models/registry.py`) implements the classic singleton pattern:

```python
class ModelRegistry:
    _instance: Optional["ModelRegistry"] = None

    def __new__(cls) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._models = {}
            cls._instance._initialized = False
        return cls._instance
```

The registry lazily initializes from `get_default_models()` on first access, loading two models:

- `primary` (id="primary") -- maps to `AZURE_OPENAI_PRIMARY_DEPLOYMENT`
- `auxiliary` (id="auxiliary") -- maps to `AZURE_OPENAI_AUXILIARY_DEPLOYMENT`

### get_model_for_operation() Routing Logic

The registry routes operations to models based on a hardcoded set of auxiliary operations:

```python
auxiliary_operations = {
    OperationType.INTENT_DETECTION,
    OperationType.CONFIDENCE_SCORING,
    OperationType.AUTO_TITLING,
    OperationType.PROFILE_EXTRACTION,
    OperationType.SUGGESTIONS,
    OperationType.EMAIL_GENERATION,
    OperationType.INDEX_SELECTION,
}

if operation in auxiliary_operations:
    return self._models.get("auxiliary")  # Fast model
else:
    return self._models.get("primary")   # Chat model
```

### Operation Type Enum

```python
class OperationType(str, Enum):
    CHAT_RESPONSE = "chat_response"
    INTENT_DETECTION = "intent_detection"
    CONFIDENCE_SCORING = "confidence_scoring"
    AUTO_TITLING = "auto_titling"
    PROFILE_EXTRACTION = "profile_extraction"
    SUGGESTIONS = "suggestions"
    EMAIL_GENERATION = "email_generation"
    INDEX_SELECTION = "index_selection"
    EMBEDDING = "embedding"
```

### Which Operations Use Which Model

| Model                                      | Operations                                                                                                                           | LLM Client Function                                   | Characteristics                                                    |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------ |
| **Primary** (GPT-5.2-chat)                 | `CHAT_RESPONSE`                                                                                                                      | `get_openai_client()`                                 | High capability, streaming, 128K context, reasoning_effort support |
| **Auxiliary** (GPT-5 Mini)                 | `INTENT_DETECTION`, `CONFIDENCE_SCORING`, `AUTO_TITLING`, `PROFILE_EXTRACTION`, `SUGGESTIONS`, `EMAIL_GENERATION`, `INDEX_SELECTION` | `get_intent_openai_client()`                          | Fast, cost-effective, JSON mode, deterministic (temp=0)            |
| **Vision** (GPT-5 Vision)                  | Image description, OCR                                                                                                               | `get_openai_client()` with vision deployment override | Multimodal, separate endpoint optional                             |
| **Doc Embedding** (text-embedding-3-large) | Document indexing embeddings (3072 dim)                                                                                              | `get_doc_openai_client()`                             | New documents, high-dimensional                                    |
| **KB Embedding** (text-embedding-ada-002)  | Legacy KB search embeddings (1536 dim)                                                                                               | `get_kb_openai_client()`                              | Legacy indexes, backward compatibility                             |

### ModelConfig Schema

Each registered model carries rich metadata:

```python
@dataclass
class ModelConfig:
    id: str                           # "primary", "auxiliary"
    deployment_name: str              # Azure deployment name
    display_name: str                 # Human-readable name
    description: str
    model_tier: ModelTier             # ECONOMY, STANDARD, PREMIUM
    user_selectable: bool = True
    default_temperature: float = 0.7
    default_max_tokens: int = 2000
    supported_operations: List[OperationType]
    pricing_info: Optional[PricingInfo]
    supports_reasoning_effort: bool = False
    base_prompt: Optional[str] = None
    base_prompt_mode: str = "prepend"  # "prepend" | "replace" | "append"
```

---

## 3. Proposed 4 User-Facing Slots

The multi-tenant platform surfaces four configurable model slots to tenant administrators. These abstract the six backend deployment slots into user-comprehensible categories.

### 3.1 Intent Slot

**Purpose**: Classification, routing, and fast analytical operations.

| Property            | Value                                                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Backend operations  | Intent detection, confidence scoring, auto-titling, profile extraction, suggestions, email generation, index selection |
| Backend mapping     | `AZURE_OPENAI_INTENT_DETECTION_DEPLOYMENT` + `AZURE_OPENAI_AUXILIARY_DEPLOYMENT`                                       |
| Optimal model class | Small/fast chat models (GPT-5 Mini, GPT-4.1-mini, GPT-4.1-nano, Claude Haiku, Gemini Flash)                            |
| Key requirements    | JSON mode support, low latency (<500ms), deterministic output (temp=0 or temp=1 for GPT-5)                             |
| Temperature         | 0.0 (or 1.0 with reasoning_effort=none for GPT-5)                                                                      |
| Max tokens          | 500-800 (structured JSON responses)                                                                                    |
| Reasoning effort    | Configurable: `none` (default), `low`, `medium`, `high`                                                                |

**Compatible model families**:

- OpenAI: GPT-5 Mini, GPT-5 Nano, GPT-4.1-mini, GPT-4.1-nano
- Anthropic: Claude 3.5 Haiku, Claude 4 Haiku
- Google: Gemini 2.0 Flash, Gemini 2.5 Flash
- DeepSeek: DeepSeek-V3

### 3.2 Chat Slot

**Purpose**: Primary response synthesis for user-facing chat interactions.

| Property            | Value                                                                                    |
| ------------------- | ---------------------------------------------------------------------------------------- |
| Backend operations  | Chat response generation (streaming), research agent planning and synthesis              |
| Backend mapping     | `AZURE_OPENAI_PRIMARY_DEPLOYMENT`                                                        |
| Optimal model class | Large/capable chat models (GPT-5.2-chat, Claude Opus, Gemini Pro)                        |
| Key requirements    | Streaming support, large context window (128K+), high-quality synthesis, source citation |
| Temperature         | 0.7 (configurable)                                                                       |
| Max tokens          | 2000-8192 (configurable)                                                                 |
| Reasoning effort    | Configurable: `none` (default), `low`, `medium`, `high`                                  |

**Compatible model families**:

- OpenAI: GPT-5.2-chat, GPT-5.1-chat, GPT-4.1, GPT-4o
- Anthropic: Claude 4 Opus, Claude 4 Sonnet, Claude 3.5 Sonnet
- Google: Gemini 2.5 Pro, Gemini 2.0 Pro
- DeepSeek: DeepSeek-R1

### 3.3 Vision Slot

**Purpose**: Image analysis, document OCR, chart/diagram understanding.

| Property            | Value                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------- |
| Backend operations  | Image description generation, document image extraction, chart data extraction        |
| Backend mapping     | `AZURE_OPENAI_VISION_DEPLOYMENT` (with optional separate endpoint/key)                |
| Optimal model class | Multimodal models with vision capability                                              |
| Key requirements    | **Must support image input** (multimodal), base64 image processing, structured output |
| Temperature         | 0.3 (factual descriptions)                                                            |
| Max tokens          | 4000 (detailed image descriptions for RAG indexing)                                   |

**Compatible model families**:

- OpenAI: GPT-5.2-chat (vision), GPT-4o (vision), GPT-4.1 (vision)
- Anthropic: Claude 4 Opus, Claude 4 Sonnet (vision-capable)
- Google: Gemini 2.5 Pro (vision), Gemini 2.0 Flash (vision)

**Constraint**: Non-multimodal models (text-only) cannot be assigned to this slot. The platform must validate multimodal capability before allowing assignment.

### 3.4 Agent Slot

**Purpose**: LLM for A2A (Agent-to-Agent) agent internal reasoning.

| Property            | Value                                                                                              |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| Backend operations  | MCP server agentic endpoints (email triage, financial analysis, procurement reasoning, scheduling) |
| Backend mapping     | Per-agent `AZURE_OPENAI_DEPLOYMENT` in each MCP server config                                      |
| Optimal model class | Varies by agent complexity; capable models for multi-step reasoning                                |
| Key requirements    | Tool/function calling support, JSON mode, potentially reasoning_effort                             |
| Temperature         | Varies by agent (0.0 for deterministic, 1.0 for creative)                                          |
| Max tokens          | 1024 (agent coordination)                                                                          |

**Current per-agent deployments**:

| MCP Server        | Deployment Name  | Reasoning Effort | Purpose                                          |
| ----------------- | ---------------- | ---------------- | ------------------------------------------------ |
| Azure AD MCP      | `mcp-azuread`    | (default)        | Email triage, calendar scheduling, people lookup |
| iLevel MCP        | `mcp-ilevel`     | `low`            | Portfolio analytics, financial data reasoning    |
| Oracle Fusion MCP | `mcp-fusion`     | (default)        | Procurement/finance agentic reasoning            |
| Perplexity MCP    | `mcp-perplexity` | `low`            | Research orchestration, citation synthesis       |

**Compatible model families**:

- OpenAI: GPT-5.2-chat, GPT-5.1-chat, GPT-5 Mini (for simpler agents)
- Anthropic: Claude 4 Sonnet, Claude 4 Opus
- Google: Gemini 2.5 Pro

**Per-agent override**: Each A2A agent can have its own deployment, allowing fine-grained model selection. A scheduling agent may use a smaller model, while a financial analysis agent requires a more capable one.

---

## 4. Backend Mapping

### Slot-to-Backend Environment Variable Mapping

| User-Facing Slot | Backend Env Var(s)                                                                              | Client Factory Function                                 | Notes                                     |
| ---------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------- |
| **Intent**       | `AZURE_OPENAI_INTENT_DEPLOYMENT`, `AZURE_OPENAI_INTENT_ENDPOINT`, `AZURE_OPENAI_INTENT_API_KEY` | `get_intent_openai_client()`, `get_intent_deployment()` | Separate endpoint for independent scaling |
| **Chat**         | `AZURE_OPENAI_PRIMARY_DEPLOYMENT`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`                  | `get_openai_client()`, `get_primary_deployment()`       | Primary endpoint, streaming               |
| **Vision**       | `AZURE_OPENAI_VISION_DEPLOYMENT`, `AZURE_OPENAI_VISION_ENDPOINT`, `AZURE_OPENAI_VISION_KEY`     | `get_openai_client()` with vision model override        | Falls back to primary endpoint            |
| **Agent**        | Per-MCP `AZURE_OPENAI_DEPLOYMENT`                                                               | Per-MCP client initialization                           | Each MCP server has own config            |

### Embedding Slots (Platform-Managed, Not Tenant-Facing)

Embedding models are platform infrastructure, not user-configurable:

| Embedding Slot | Backend Env Var                         | Client Function           | Dimension |
| -------------- | --------------------------------------- | ------------------------- | --------- |
| Doc Embedding  | `AZURE_OPENAI_DOC_EMBEDDING_DEPLOYMENT` | `get_doc_openai_client()` | 3072      |
| KB Embedding   | `AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT`  | `get_kb_openai_client()`  | 1536      |

Embedding models are excluded from tenant-facing slots because:

1. Changing embedding models requires full re-indexing of all documents
2. Mixed embedding dimensions break vector search compatibility
3. Embedding model selection is an infrastructure decision, not a user preference

### Auxiliary Deployment Consolidation

The current codebase has both `AZURE_OPENAI_AUXILIARY_DEPLOYMENT` and `AZURE_OPENAI_INTENT_DETECTION_DEPLOYMENT` (both defaulting to `intent5`). In the multi-tenant model, these consolidate under the **Intent Slot**, since all auxiliary operations (titling, profiling, suggestions, email, index selection, confidence scoring) share the same performance characteristics as intent detection: fast, structured, cost-optimized.

---

## 5. Model Capability Validation

### Capability Requirements Matrix

| Capability                 | Intent Slot  |  Chat Slot   | Vision Slot  |  Agent Slot  |
| -------------------------- | :----------: | :----------: | :----------: | :----------: |
| Text input/output          |   Required   |   Required   |   Required   |   Required   |
| Image input (multimodal)   |      --      |      --      | **Required** |      --      |
| Streaming                  |      --      | **Required** |      --      |      --      |
| JSON mode                  | **Required** |      --      |      --      | **Required** |
| Tool/function calling      |      --      |      --      |      --      | **Required** |
| Large context (128K+)      |  Preferred   | **Required** |      --      |  Preferred   |
| Reasoning effort parameter |   Optional   |   Optional   |      --      |   Optional   |
| Low latency (<500ms)       | **Required** |      --      |      --      |  Preferred   |

### Model Family Compatibility Matrix

| Model Family               | Intent |     Chat      | Vision |    Agent     |  Embedding  |
| -------------------------- | :----: | :-----------: | :----: | :----------: | :---------: |
| **GPT-5.2-chat**           |  Yes   |      Yes      |  Yes   |     Yes      |     No      |
| **GPT-5 Mini**             |  Yes   | Yes (limited) |   No   | Yes (simple) |     No      |
| **GPT-5 Nano**             |  Yes   |      No       |   No   |      No      |     No      |
| **GPT-4.1**                |  Yes   |      Yes      |  Yes   |     Yes      |     No      |
| **GPT-4.1-mini**           |  Yes   | Yes (limited) |   No   |     Yes      |     No      |
| **GPT-4.1-nano**           |  Yes   |      No       |   No   |      No      |     No      |
| **Claude 4 Opus**          |  Yes   |      Yes      |  Yes   |     Yes      |     No      |
| **Claude 4 Sonnet**        |  Yes   |      Yes      |  Yes   |     Yes      |     No      |
| **Claude 3.5 Haiku**       |  Yes   |      No       |   No   | Yes (simple) |     No      |
| **Gemini 2.5 Pro**         |  Yes   |      Yes      |  Yes   |     Yes      |     No      |
| **Gemini 2.0 Flash**       |  Yes   | Yes (limited) |  Yes   |     Yes      |     No      |
| **DeepSeek-R1**            |  Yes   |      Yes      |   No   |     Yes      |     No      |
| **text-embedding-3-large** |   No   |      No       |   No   |      No      | Yes (3072d) |
| **text-embedding-ada-002** |   No   |      No       |   No   |      No      | Yes (1536d) |

### Validation Rules

1. **Vision slot**: The platform must reject assignment of non-multimodal models. Validation checks the model's capability metadata for `supports_vision: true`.
2. **Embedding models**: Cannot be assigned to any of the four user-facing slots. Embeddings are a separate infrastructure category.
3. **Reasoning effort**: Only applicable to OpenAI o-series and GPT-5 models. The platform silently ignores `reasoning_effort` for models that do not support it.
4. **Streaming**: Chat slot models must support streaming output. Non-streaming models would break the SSE response pipeline.
5. **JSON mode**: Intent and Agent slots require models with structured output / JSON mode support for reliable parsing.

---

## 6. Per-Plan Tier Defaults

### Platform Default Model Assignments

The platform provides sensible defaults for each slot that balance performance and cost:

| Slot   | Platform Default       | Tier    | Rationale                                  |
| ------ | ---------------------- | ------- | ------------------------------------------ |
| Intent | GPT-5 Mini             | Economy | Fast, cheap, sufficient for classification |
| Chat   | GPT-5.2-chat           | Premium | Highest quality for user-facing responses  |
| Vision | GPT-5.2-chat (vision)  | Premium | Multimodal required, best accuracy         |
| Agent  | GPT-5.1-chat (per MCP) | Premium | Reasoning quality for agentic workflows    |

### Tenant Override Rules by Plan Tier

| Plan             | Monthly Price | Intent Override | Chat Override | Vision Override | Agent Override | BYOLLM |
| ---------------- | :-----------: | :-------------: | :-----------: | :-------------: | :------------: | :----: |
| **Starter**      |      Low      |       No        |      No       |       No        |       No       |   No   |
| **Professional** |    Medium     |       Yes       |      Yes      |       No        |       No       |   No   |
| **Enterprise**   |     High      |       Yes       |      Yes      |       Yes       |      Yes       |  Yes   |

### Detailed Plan Capabilities

**Starter Plan**:

- Uses all platform defaults
- No model customization
- Cost predictable (platform absorbs model selection complexity)
- Tenant admin sees model names in read-only mode

**Professional Plan**:

- Can override Intent and Chat slot models from the **platform-approved model library**
- Vision and Agent remain platform-managed
- Useful for tenants who want to optimize cost (downgrade Chat to a cheaper model) or quality (upgrade Intent to a more capable model)
- Overrides persist per-tenant in Cosmos DB configuration

**Enterprise Plan**:

- Full override of all four slots from the approved library
- Per-agent model selection (different model per MCP server)
- **BYOLLM (Bring Your Own LLM)**: Tenant provides their own Azure OpenAI endpoint, API key, and deployment name
- Platform validates connectivity and capability before accepting BYOLLM configuration
- BYOLLM tenants are responsible for their own Azure OpenAI costs

### Override Storage Model

```
Cosmos DB: tenants/{tenant_id}
{
  "model_overrides": {
    "intent": {
      "deployment_name": "custom-intent-model",
      "endpoint": null,         // null = use platform endpoint
      "api_key": null           // null = use platform key
    },
    "chat": {
      "deployment_name": "gpt-5.2-chat",
      "endpoint": null,
      "api_key": null
    },
    "vision": null,              // null = use platform default
    "agents": {
      "mcp-azuread": {
        "deployment_name": "custom-azuread-model"
      }
    }
  },
  "byollm": {                    // Enterprise only
    "enabled": false,
    "endpoint": "",
    "api_key_ref": "",           // Key Vault reference, never stored raw
    "validated_at": null
  }
}
```

---

## 7. 80/15/5 Applied to Model Slots

### 80% Platform-Provided (Zero Configuration)

The platform provides the full model management infrastructure out of the box:

| Component                     | Platform Provides                                                                       |
| ----------------------------- | --------------------------------------------------------------------------------------- |
| **Model Registry**            | Singleton registry with capability metadata, pricing info, operation routing            |
| **Capability Validation**     | Automated checks: multimodal for vision, streaming for chat, JSON mode for intent/agent |
| **Routing Logic**             | `get_model_for_operation()` routes each operation type to the correct slot              |
| **Cost Tracking**             | Per-model pricing (`PricingInfo`), per-query cost calculation via `cost_calculator.py`  |
| **Context Window Management** | Token budget management per model via `ContextWindowManager`                            |
| **Fallback Chains**           | Automatic failover (primary -> auxiliary -> search results -> graceful error)           |
| **Reasoning Effort**          | Per-slot reasoning_effort parameter, tuned per operation type                           |
| **Prompt Caching**            | Azure OpenAI prompt caching integration (cacheable system messages)                     |

All Starter plan tenants get this complete stack with zero configuration.

### 15% Tenant-Configurable (Per-Slot Selection)

Professional and Enterprise tenants can select models per slot from the platform-approved library:

| Customization               | Scope                                               | Guard Rails                         |
| --------------------------- | --------------------------------------------------- | ----------------------------------- |
| **Select model per slot**   | Intent, Chat (Professional); all slots (Enterprise) | Must pass capability validation     |
| **Reasoning effort tuning** | Per-slot reasoning_effort level                     | Constrained to none/low/medium/high |
| **Temperature override**    | Per-slot default temperature                        | Constrained to 0.0-2.0              |
| **Max tokens override**     | Per-slot max_tokens                                 | Constrained to model maximum        |
| **Per-agent model**         | Different model per MCP agent (Enterprise)          | Must support tool calling           |

The platform-approved model library is curated by the platform admin. It contains models that have been tested for compatibility, pricing has been confirmed, and capability metadata is accurate. Tenants select from this library -- they do not provide arbitrary model names.

### 5% BYOLLM (Full Custom)

Enterprise tenants with unique requirements can bring their own LLM infrastructure:

| Customization         | Details                                                                     |
| --------------------- | --------------------------------------------------------------------------- |
| **Custom endpoint**   | Tenant's own Azure OpenAI resource (or compatible API)                      |
| **Custom API key**    | Stored securely in Azure Key Vault (key reference, never raw)               |
| **Custom deployment** | Any deployment name on their resource                                       |
| **Custom models**     | Models not in the platform library (private fine-tuned models, self-hosted) |
| **Cost isolation**    | Tenant pays their own Azure OpenAI bills directly                           |

**BYOLLM Validation Flow**:

1. Tenant provides endpoint + key + deployment name
2. Platform sends a test completion request to validate connectivity
3. Platform sends a test vision request (if vision slot) to validate multimodal capability
4. Platform records validation timestamp and capability profile
5. Periodic re-validation ensures endpoint remains healthy

**BYOLLM Limitations**:

- Platform cannot track token costs for BYOLLM endpoints (no billing data)
- Platform cannot guarantee latency SLAs for external endpoints
- Tenant is responsible for rate limits, quotas, and availability
- Platform logs operation type and latency, but not token counts

---

## Pricing Reference

Current model pricing used in cost tracking (`cost_calculator.py`):

| Model                  | Input (per 1M tokens) | Output (per 1M tokens) | Tier    |
| ---------------------- | :-------------------: | :--------------------: | ------- |
| GPT-5.2-chat           |         $2.50         |         $10.00         | Premium |
| GPT-5.1-chat           |         $2.50         |         $10.00         | Premium |
| GPT-5 Mini             |         $0.15         |         $0.60          | Economy |
| GPT-5 Nano             |         $0.15         |         $0.60          | Economy |
| GPT-4.1                |         $2.50         |         $10.00         | Premium |
| GPT-4.1-mini           |         $0.15         |         $0.60          | Economy |
| text-embedding-3-large |         $0.13         |           --           | Infra   |
| text-embedding-ada-002 |         $0.10         |           --           | Infra   |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
**Source**: `aihub2/src/backend/api-service/app/core/config.py`, `app/models/registry.py`, `app/models/defaults.py`, `app/models/schemas.py`, `app/services/openai_client.py`, `app/modules/chat/llm_generation.py`, `app/modules/chat/combined_intent_service.py`, `app/modules/chat/confidence_scoring.py`, `app/modules/chat/agents/config.py`, `backend/shared/aihub_shared/services/vision_description.py`, MCP server configs (azure-ad, ilevel, oracle-fusion, perplexity)
