# Multi-Provider LLM Architecture

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: LLM provider abstraction, per-tenant selection, BYOLLM support

---

## Overview

The current system is hardcoded to Azure OpenAI as its sole LLM provider. Multi-tenancy requires a provider abstraction layer that supports platform-level provider management, per-tenant provider selection, and Bring Your Own LLM (BYOLLM) for tenants that want to use their own API keys. This document designs the complete architecture for multi-provider LLM management.

---

## Current State: Azure OpenAI Only

### Evidence from Source Code

**Single provider hardcoded** in `app/services/openai_client.py:17`:

```python
from openai import AsyncAzureOpenAI  # ONLY LLM SDK import in entire codebase
```

**Global singleton factory** in `app/services/openai_client.py:29-46`:

```python
_factory: Optional[OpenAIClientFactory] = None

def _get_factory() -> OpenAIClientFactory:
    global _factory
    if _factory is None:
        config = create_openai_client_config_from_settings(settings)
        _factory = create_openai_client_factory(config)
    return _factory
```

**Immutable `@lru_cache` on Settings** in `app/core/config.py:489-492`:

```python
@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # Called once at startup, cached forever

settings = get_settings()  # Global singleton -- cannot change per-tenant
```

### Current Deployment Architecture

From `10-kaizen-extension-analysis.md` Part 1:

```
┌─────────────────────────────────────────────────────┐
│         Primary Azure OpenAI Resource               │
│  (AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY)        │
├─────────────────────────────────────────────────────┤
│ ├─ mingai-main (GPT-5.2-chat)           [CHAT]     │
│ ├─ intent5 (GPT-5-mini)                  [INTENT]   │
│ └─ text-embedding-3-large                [DOCS]     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│    Secondary KB Resource (Optional)                  │
│  (AZURE_OPENAI_KB_ENDPOINT + KEY)                   │
├─────────────────────────────────────────────────────┤
│ └─ text-embedding-ada-002                [KB]       │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│   Intent Detection Resource (Optional)               │
│  (AZURE_OPENAI_INTENT_ENDPOINT + KEY)               │
├─────────────────────────────────────────────────────┤
│ └─ intent5 (GPT-5-mini)                 [INTENT]    │
└─────────────────────────────────────────────────────┘
```

### Current Config Fields (config.py:82-176)

| Field                                      | Default                    | Purpose                              |
| ------------------------------------------ | -------------------------- | ------------------------------------ |
| `azure_openai_endpoint`                    | `""`                       | Primary endpoint (config.py:83)      |
| `azure_openai_key`                         | `""`                       | Primary API key (config.py:84)       |
| `azure_openai_api_version`                 | `"2024-12-01-preview"`     | API version (config.py:85)           |
| `azure_openai_primary_deployment`          | `"mingai-main"`            | Chat model (config.py:86-89)         |
| `azure_openai_auxiliary_deployment`        | `"intent5"`                | Fast model (config.py:90-93)         |
| `azure_openai_intent_detection_deployment` | `"intent5"`                | Intent model (config.py:94-97)       |
| `azure_openai_vision_deployment`           | `"gpt-vision"`             | Vision model (config.py:98-101)      |
| `azure_openai_doc_embedding_deployment`    | `"text-embedding-3-large"` | Doc embeddings (config.py:110)       |
| `azure_openai_kb_endpoint`                 | `""`                       | KB resource (config.py:174)          |
| `azure_openai_kb_key`                      | `""`                       | KB key (config.py:175)               |
| `azure_openai_kb_embedding_deployment`     | `"text-embedding-ada-002"` | KB embeddings (config.py:176)        |
| `azure_openai_chat_reasoning_effort`       | `"none"`                   | Reasoning effort (config.py:167-171) |
| `azure_openai_intent_reasoning_effort`     | `"none"`                   | Intent reasoning (config.py:147-151) |

### Five Critical Limitations

1. **No provider abstraction**: Switching providers requires code changes (10-kaizen-extension-analysis.md:1061)
2. **No multi-tenant awareness**: Config is global, all tenants use same provider (10-kaizen-extension-analysis.md:1062)
3. **No runtime config changes**: `@lru_cache` prevents any config updates (config.py:489)
4. **No provider fallback**: If Azure OpenAI fails, no automatic switch (10-kaizen-extension-analysis.md:1065)
5. **No cost attribution per tenant**: Cannot bill different providers to different tenants (10-kaizen-extension-analysis.md:1066)

### Missing Providers (10-kaizen-extension-analysis.md:147-195)

| Provider               | Status  | Evidence                                 |
| ---------------------- | ------- | ---------------------------------------- |
| OpenAI (direct)        | Missing | No `AsyncOpenAI` import anywhere         |
| Anthropic Claude       | Missing | No `anthropic` SDK reference             |
| Deepseek               | Missing | No `deepseek` reference                  |
| Alibaba Qwen/DashScope | Missing | No `alibaba` or `dashscope` reference    |
| Bytedance Ark/Doubao   | Missing | No `bytedance` or `volcengine` reference |
| Google Gemini          | Missing | No `google.generativeai` reference       |

---

## Target Architecture: Multi-Provider with Tenant Selection

### Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                    Platform Admin Layer                              │
│  Manages global provider catalog + credentials                      │
│  POST /v1/platform/providers                                        │
│  ├─ Azure OpenAI  ✅ active (endpoint + key in vault)              │
│  ├─ OpenAI Direct ✅ active (API key in vault)                     │
│  ├─ Anthropic     ✅ active (API key in vault)                     │
│  ├─ Deepseek      ✅ active (API key in vault)                     │
│  ├─ DashScope     ⏸  disabled                                      │
│  ├─ Doubao/Ark    ⏸  disabled                                      │
│  └─ Gemini        ⏸  disabled                                      │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Tenant Admin Layer                                │
│  Selects from platform-approved providers OR configures BYOLLM     │
│                                                                    │
│  Tenant "Acme Corp" (Professional plan):                           │
│  ├─ Primary: Azure OpenAI (platform-provided)                      │
│  ├─ Fallback: OpenAI Direct (platform-provided)                   │
│  └─ BYOLLM: Anthropic (tenant's own API key, encrypted)           │
│                                                                    │
│  Tenant "BigCorp" (Enterprise plan):                               │
│  ├─ Primary: Anthropic (platform-provided)                        │
│  └─ BYOLLM: Azure OpenAI (BigCorp's own Azure subscription)      │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│              LLM Client Manager (Runtime Resolution)               │
│                                                                    │
│  Per-request flow:                                                  │
│  1. Extract tenant_id from JWT                                     │
│  2. Load tenant's LLM config (cached in Redis, 5-min TTL)         │
│  3. Resolve provider: platform-provided or BYOLLM                  │
│  4. Get or create client from per-tenant cache                     │
│  5. Map use_case → provider-specific model/deployment name         │
│  6. Execute with provider-appropriate SDK call                     │
│  7. Log usage for cost attribution                                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## Provider Abstraction Interface

### Use Cases (Operation Types)

The current `ModelRegistry` (app/models/registry.py:16-100) already maps operations to models. The abstraction extends this per-tenant:

| Use Case           | Current Azure Deployment     | Purpose                      |
| ------------------ | ---------------------------- | ---------------------------- |
| `chat_response`    | `mingai-main` (GPT-5.2-chat) | Main conversational AI       |
| `intent_detection` | `intent5` (GPT-5-mini)       | Fast intent classification   |
| `doc_embedding`    | `text-embedding-3-large`     | Document embedding at ingest |
| `kb_embedding`     | `text-embedding-ada-002`     | KB search embedding          |
| `vision`           | `gpt-vision`                 | Image analysis               |

### Provider Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional

@dataclass
class ProviderConfig:
    """Provider configuration loaded from database."""
    provider_type: str        # "azure_openai", "openai", "anthropic", etc.
    endpoint: Optional[str]   # Endpoint URL (Azure) or None (others)
    api_key: str              # Decrypted API key
    models: Dict[str, str]    # use_case -> model/deployment name
    options: Dict             # Provider-specific: api_version, reasoning_effort, etc.

class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        stream: bool = True,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion tokens."""

    @abstractmethod
    async def embedding(
        self,
        text: str,
        model: str,
    ) -> List[float]:
        """Generate text embedding."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check provider connectivity."""

    @abstractmethod
    def supports_reasoning_effort(self) -> bool:
        """Whether this provider supports reasoning_effort parameter."""

    @abstractmethod
    def supports_vision(self) -> bool:
        """Whether this provider supports vision/multimodal input."""
```

### Provider Implementations

```python
class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider (current implementation, refactored)."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncAzureOpenAI
        self.client = AsyncAzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.options.get("api_version", "2024-12-01-preview"),
        )
        self.models = config.models
        self.options = config.options

    async def chat_completion(self, messages, model, **kwargs):
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        extra_body = {}
        if reasoning_effort and reasoning_effort != "none":
            extra_body["reasoning_effort"] = reasoning_effort

        response = await self.client.chat.completions.create(
            model=model,  # Azure deployment name
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_completion_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
            extra_body=extra_body if extra_body else None,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model,
            input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return True  # Azure OpenAI supports reasoning_effort

    def supports_vision(self) -> bool:
        return True


class OpenAIProvider(LLMProvider):
    """OpenAI direct API provider."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=config.api_key)
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        extra_body = {}
        if reasoning_effort and reasoning_effort != "none":
            extra_body["reasoning_effort"] = reasoning_effort

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
            extra_body=extra_body if extra_body else None,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model,
            input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return True  # OpenAI o-series supports reasoning_effort

    def supports_vision(self) -> bool:
        return True


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, config: ProviderConfig):
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=config.api_key)
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        # Anthropic uses different message format:
        # - system message is a separate parameter
        # - no "system" role in messages array
        system_msg = None
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)

        async with self.client.messages.stream(
            model=model,
            messages=user_messages,
            system=system_msg or "",
            max_tokens=kwargs.get("max_tokens", 8192),
            temperature=kwargs.get("temperature", 0.7),
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def embedding(self, text, model):
        # Anthropic does not have embedding API -- use Voyage AI or fallback
        raise NotImplementedError(
            "Anthropic does not provide embeddings. "
            "Configure a separate embedding provider."
        )

    def supports_reasoning_effort(self) -> bool:
        return False  # Claude uses extended thinking, different parameter

    def supports_vision(self) -> bool:
        return True  # Claude supports vision


class DeepseekProvider(LLMProvider):
    """Deepseek provider (OpenAI-compatible API)."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.endpoint or "https://api.deepseek.com/v1",
        )
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model, input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return False


class DashScopeProvider(LLMProvider):
    """Alibaba DashScope/Qwen provider."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.endpoint or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model, input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return True  # Qwen-VL supports vision


class DoubaoProvider(LLMProvider):
    """Bytedance Ark/Doubao provider."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.endpoint or "https://ark.cn-beijing.volces.com/api/v3",
        )
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model, input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return True


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, config: ProviderConfig):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.models = config.models

    async def chat_completion(self, messages, model, **kwargs):
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embedding(self, text, model):
        response = await self.client.embeddings.create(
            model=model, input=text,
        )
        return response.data[0].embedding

    def supports_reasoning_effort(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return True
```

### Provider Registry

```python
PROVIDER_REGISTRY: Dict[str, type] = {
    "azure_openai": AzureOpenAIProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepseekProvider,
    "dashscope": DashScopeProvider,
    "doubao": DoubaoProvider,
    "gemini": GeminiProvider,
}
```

---

## Platform Admin: Global Provider Configuration

### Provider Data Model

Stored in PostgreSQL `llm_providers` table with RLS (PK: `id UUID`):

```python
# llm_providers container
{
    "id": "provider-uuid",
    "provider_type": "azure_openai",            # Registry key
    "display_name": "Azure OpenAI (GPT-5.2)",
    "description": "Platform-managed Azure OpenAI with GPT-5.2-chat",
    "endpoint": "https://mingai-prod.openai.azure.com/",
    "api_key_vault_ref": "vault://mingai/azure-openai-key",  # Key Vault reference
    "is_enabled": True,
    "is_default": True,                         # Default for new tenants
    "models": {
        "chat_response": "mingai-main",         # GPT-5.2-chat
        "intent_detection": "intent5",          # GPT-5-mini
        "doc_embedding": "text-embedding-3-large",
        "kb_embedding": "text-embedding-ada-002",
        "vision": "gpt-vision",
    },
    "options": {
        "api_version": "2024-12-01-preview",
        "reasoning_effort": "none",
        "max_tokens": 8192,
        "temperature": 0.7,
    },
    "pricing": {
        "chat_input_per_1k": 0.002,
        "chat_output_per_1k": 0.008,
        "intent_input_per_1k": 0.0004,
        "intent_output_per_1k": 0.0016,
        "embedding_per_1k": 0.0001,
    },
    "rate_limits": {
        "requests_per_minute": 1000,
        "tokens_per_minute": 500000,
    },
    "created_at": "2026-03-04T00:00:00Z",
    "updated_at": "2026-03-04T00:00:00Z",
    "created_by": "platform-admin-uuid",
}
```

### Provider Catalog (All Supported)

| Provider          | Type Key       | Default Models                   | Embedding Support      | Vision        | reasoning_effort |
| ----------------- | -------------- | -------------------------------- | ---------------------- | ------------- | ---------------- |
| Azure OpenAI      | `azure_openai` | GPT-5.2-chat, GPT-5-mini         | text-embedding-3-large | Yes           | Yes              |
| OpenAI Direct     | `openai`       | gpt-5, gpt-5-mini                | text-embedding-3-large | Yes           | Yes (o-series)   |
| Anthropic         | `anthropic`    | claude-opus-4, claude-sonnet-4   | No (use separate)      | Yes           | No               |
| Deepseek          | `deepseek`     | deepseek-chat, deepseek-coder    | deepseek-embedding     | No            | No               |
| Alibaba DashScope | `dashscope`    | qwen-max, qwen-plus              | text-embedding-v3      | Yes (Qwen-VL) | No               |
| Bytedance Doubao  | `doubao`       | doubao-pro, doubao-lite          | doubao-embedding       | Yes           | No               |
| Google Gemini     | `gemini`       | gemini-2.0-flash, gemini-2.0-pro | text-embedding-004     | Yes           | No               |

### Platform Admin API

From `01-admin-hierarchy.md:144-152`:

```python
@router.get("/api/v1/platform/providers")
async def list_providers(
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """List all configured LLM providers."""
    providers = await ProviderService.list_all()
    return [
        {
            "id": p.id,
            "provider_type": p.provider_type,
            "display_name": p.display_name,
            "is_enabled": p.is_enabled,
            "is_default": p.is_default,
            "models": p.models,
            "api_key_configured": bool(p.api_key_vault_ref),  # Never expose key
        }
        for p in providers
    ]


@router.put("/api/v1/platform/providers/{provider_id}")
async def configure_provider(
    provider_id: str,
    request: ProviderConfigRequest,
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """
    Configure a global LLM provider.

    Steps:
    1. Validate provider_type is in PROVIDER_REGISTRY
    2. Test connectivity with provider
    3. Encrypt API key and store in vault
    4. Update provider record in database
    5. Invalidate Redis cache for all tenants using this provider
    """
    # Validate provider type
    if request.provider_type not in PROVIDER_REGISTRY:
        raise HTTPException(400, f"Unsupported provider: {request.provider_type}")

    # Test connectivity
    test_provider = PROVIDER_REGISTRY[request.provider_type](
        ProviderConfig(
            provider_type=request.provider_type,
            endpoint=request.endpoint,
            api_key=request.api_key,
            models=request.models,
            options=request.options or {},
        )
    )
    is_healthy = await test_provider.health_check()
    if not is_healthy:
        raise HTTPException(400, "Provider connectivity test failed")

    # Store key in vault
    vault_ref = await vault_service.store_secret(
        name=f"llm-provider-{provider_id}",
        value=request.api_key,
    )

    # Update database
    await ProviderService.update(
        provider_id=provider_id,
        endpoint=request.endpoint,
        api_key_vault_ref=vault_ref,
        models=request.models,
        options=request.options,
        updated_by=admin.user_id,
    )

    # Invalidate caches
    await invalidate_provider_caches(provider_id)
```

---

## Tenant Admin: Provider Selection + BYOLLM

### Tenant LLM Settings Data Model

Stored in the tenant record:

```python
# tenants container -- llm_config field
{
    "id": "tenant-uuid",
    "name": "Acme Corporation",
    # ... other tenant fields from 01-admin-hierarchy.md ...
    "llm_config": {
        "primary_provider_id": "platform-azure-provider-uuid",
        "fallback_provider_id": "platform-openai-provider-uuid",
        "byollm": {
            "enabled": False,
            "provider_type": None,
            "api_key_vault_ref": None,
            "endpoint": None,
            "models": None,
        },
        "reasoning_effort_override": None,  # null = use provider default
        "temperature_override": None,
        "max_tokens_override": None,
    },
}
```

### Tenant Admin API

From `01-admin-hierarchy.md:256-261`:

```python
@router.get("/api/v1/admin/providers")
async def list_available_providers(
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """List LLM providers available to this tenant."""
    # Get platform-enabled providers
    platform_providers = await ProviderService.list_enabled()

    # Get tenant's current selection
    tenant = await TenantService.get(tenant_id)
    llm_config = tenant.llm_config

    return {
        "current_primary": llm_config.primary_provider_id,
        "current_fallback": llm_config.fallback_provider_id,
        "byollm_enabled": llm_config.byollm.enabled,
        "byollm_allowed": tenant.quotas.byollm_allowed,  # Plan-based
        "available_providers": [
            {
                "id": p.id,
                "provider_type": p.provider_type,
                "display_name": p.display_name,
                "models": p.models,
                "supports_vision": PROVIDER_REGISTRY[p.provider_type]
                    .__init__.__doc__,  # capability check
            }
            for p in platform_providers
        ],
    }


@router.post("/api/v1/admin/providers/{provider_id}/enable")
async def select_provider(
    provider_id: str,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Select a platform provider as primary for this tenant."""
    provider = await ProviderService.get(provider_id)
    if not provider or not provider.is_enabled:
        raise HTTPException(404, "Provider not available")

    await TenantService.update_llm_config(
        tenant_id=tenant_id,
        primary_provider_id=provider_id,
    )

    # Invalidate tenant's LLM client cache
    await invalidate_tenant_llm_cache(tenant_id)


@router.put("/api/v1/admin/providers/byollm")
async def configure_byollm(
    request: BYOLLMRequest,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Configure Bring Your Own LLM keys.

    From 01-admin-hierarchy.md:318-336.
    Keys are encrypted and stored in vault, scoped to tenant.
    """
    tenant = await TenantService.get(tenant_id)
    if not tenant.quotas.byollm_allowed:
        raise HTTPException(403, "BYOLLM not available on your plan")

    # Validate provider type
    if request.provider not in PROVIDER_REGISTRY:
        raise HTTPException(400, f"Unsupported provider: {request.provider}")

    # Test tenant's API key
    test_provider = PROVIDER_REGISTRY[request.provider](
        ProviderConfig(
            provider_type=request.provider,
            endpoint=request.endpoint,
            api_key=request.api_key,
            models=request.models or {},
            options={},
        )
    )
    is_healthy = await test_provider.health_check()
    if not is_healthy:
        raise HTTPException(400, "Could not connect with provided credentials")

    # Store key in vault (tenant-scoped)
    vault_ref = await vault_service.store_secret(
        name=f"byollm-{tenant_id}-{request.provider}",
        value=request.api_key,
    )

    await TenantService.update_llm_config(
        tenant_id=tenant_id,
        byollm={
            "enabled": True,
            "provider_type": request.provider,
            "api_key_vault_ref": vault_ref,
            "endpoint": request.endpoint,
            "models": request.models,
        },
    )
```

---

## LLM Client Manager: Per-Request Resolution

### Resolution Flow

```python
class LLMClientManager:
    """
    Manages LLM provider resolution per-tenant, per-request.

    Replaces the current global OpenAIClientFactory singleton.
    """

    def __init__(self, vault_service, redis_client):
        self.vault = vault_service
        self.redis = redis_client
        self._provider_cache: Dict[str, LLMProvider] = {}  # cache_key -> provider
        self._config_cache_ttl = 300  # 5 minutes

    async def get_provider(
        self,
        tenant_id: str,
        use_case: str = "chat_response",
    ) -> tuple[LLMProvider, str]:
        """
        Get LLM provider and model name for a tenant + use case.

        Resolution order:
        1. BYOLLM (if enabled and has the use_case model)
        2. Tenant's primary provider
        3. Tenant's fallback provider
        4. Platform default provider

        Returns:
            (provider_instance, model_name)
        """
        # Load tenant LLM config (cached in Redis)
        config = await self._get_tenant_config(tenant_id)

        # Try BYOLLM first
        if config.byollm and config.byollm.enabled:
            byollm_model = config.byollm.models.get(use_case)
            if byollm_model:
                provider = await self._get_or_create_provider(
                    cache_key=f"byollm:{tenant_id}",
                    provider_type=config.byollm.provider_type,
                    endpoint=config.byollm.endpoint,
                    vault_ref=config.byollm.api_key_vault_ref,
                    models=config.byollm.models,
                    options={},
                )
                return provider, byollm_model

        # Try primary provider
        if config.primary_provider_id:
            platform_provider = await self._get_platform_provider(config.primary_provider_id)
            if platform_provider:
                model = platform_provider.models.get(use_case)
                if model:
                    provider = await self._get_or_create_provider(
                        cache_key=f"platform:{config.primary_provider_id}",
                        provider_type=platform_provider.provider_type,
                        endpoint=platform_provider.endpoint,
                        vault_ref=platform_provider.api_key_vault_ref,
                        models=platform_provider.models,
                        options=platform_provider.options,
                    )
                    return provider, model

        # Try fallback
        if config.fallback_provider_id:
            fallback = await self._get_platform_provider(config.fallback_provider_id)
            if fallback:
                model = fallback.models.get(use_case)
                if model:
                    provider = await self._get_or_create_provider(
                        cache_key=f"platform:{config.fallback_provider_id}",
                        provider_type=fallback.provider_type,
                        endpoint=fallback.endpoint,
                        vault_ref=fallback.api_key_vault_ref,
                        models=fallback.models,
                        options=fallback.options,
                    )
                    return provider, model

        # Platform default
        default = await self._get_default_provider()
        model = default.models.get(use_case)
        provider = await self._get_or_create_provider(
            cache_key=f"platform:{default.id}",
            provider_type=default.provider_type,
            endpoint=default.endpoint,
            vault_ref=default.api_key_vault_ref,
            models=default.models,
            options=default.options,
        )
        return provider, model

    async def _get_or_create_provider(
        self, cache_key, provider_type, endpoint, vault_ref, models, options,
    ) -> LLMProvider:
        """Get cached provider or create new one."""
        if cache_key not in self._provider_cache:
            api_key = await self.vault.get_secret(vault_ref)
            config = ProviderConfig(
                provider_type=provider_type,
                endpoint=endpoint,
                api_key=api_key,
                models=models,
                options=options,
            )
            provider_class = PROVIDER_REGISTRY[provider_type]
            self._provider_cache[cache_key] = provider_class(config)
        return self._provider_cache[cache_key]
```

---

## Reasoning Effort Routing Per Provider

### Current Implementation (config.py:147-171)

```python
azure_openai_intent_reasoning_effort: str = Field(default="none")
azure_openai_chat_reasoning_effort: str = Field(default="none")
```

These are global settings. The multi-tenant design allows per-tenant override:

### Per-Tenant Reasoning Effort

```python
# Tenant LLM config
"llm_config": {
    "reasoning_effort_override": "medium",  # Overrides provider default
}
```

### Provider-Specific Handling

| Provider      | Reasoning Parameter                                | Implementation    |
| ------------- | -------------------------------------------------- | ----------------- |
| Azure OpenAI  | `extra_body={"reasoning_effort": "medium"}`        | Direct support    |
| OpenAI Direct | `extra_body={"reasoning_effort": "medium"}`        | o-series models   |
| Anthropic     | `thinking={"type": "enabled", "budget_tokens": N}` | Extended thinking |
| Deepseek      | Not supported                                      | Ignored           |
| DashScope     | Not supported                                      | Ignored           |
| Doubao        | Not supported                                      | Ignored           |
| Gemini        | `generation_config={"thinking_mode": True}`        | Thinking mode     |

```python
async def apply_reasoning_effort(
    provider: LLMProvider,
    reasoning_effort: Optional[str],
    kwargs: dict,
) -> dict:
    """Apply reasoning effort parameter in provider-specific way."""
    if not reasoning_effort or reasoning_effort == "none":
        return kwargs

    if not provider.supports_reasoning_effort():
        return kwargs  # Silently skip for unsupported providers

    if isinstance(provider, (AzureOpenAIProvider, OpenAIProvider)):
        kwargs["reasoning_effort"] = reasoning_effort
    elif isinstance(provider, AnthropicProvider):
        # Map reasoning_effort to Claude's thinking budget
        budget_map = {"low": 2048, "medium": 8192, "high": 32768}
        kwargs["thinking_budget"] = budget_map.get(reasoning_effort, 8192)

    return kwargs
```

---

## Replacing `@lru_cache` on Settings

### The Problem (config.py:489-495)

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()  # Loaded once, cached forever

settings = get_settings()  # Global immutable singleton
```

Every LLM config field (deployment names, endpoints, keys, reasoning effort) is frozen at startup.

### The Solution: Database-Driven Config with Redis Cache

```python
# Phase 1: Keep settings for non-LLM config (server, CORS, Redis URL)
# Phase 2: Move LLM config to database + Redis cache

class TenantLLMConfigCache:
    """Redis-cached tenant LLM configuration."""

    CACHE_PREFIX = "mingai:llm-config:"
    CACHE_TTL = 300  # 5 minutes

    @classmethod
    async def get(cls, tenant_id: str) -> Optional[dict]:
        redis = get_redis()
        cached = await redis.get(f"{cls.CACHE_PREFIX}{tenant_id}")
        if cached:
            return json.loads(cached)
        return None

    @classmethod
    async def set(cls, tenant_id: str, config: dict):
        redis = get_redis()
        await redis.set(
            f"{cls.CACHE_PREFIX}{tenant_id}",
            json.dumps(config),
            ex=cls.CACHE_TTL,
        )

    @classmethod
    async def invalidate(cls, tenant_id: str):
        redis = get_redis()
        await redis.delete(f"{cls.CACHE_PREFIX}{tenant_id}")
```

### Migration: `settings.azure_openai_*` to Database

| Current Usage                                 | New Pattern                                  |
| --------------------------------------------- | -------------------------------------------- |
| `settings.azure_openai_endpoint`              | `provider_config.endpoint` (from DB)         |
| `settings.azure_openai_key`                   | `vault.get_secret(ref)` (from Key Vault)     |
| `settings.azure_openai_primary_deployment`    | `provider_config.models["chat_response"]`    |
| `settings.azure_openai_auxiliary_deployment`  | `provider_config.models["intent_detection"]` |
| `settings.azure_openai_chat_reasoning_effort` | `tenant_config.reasoning_effort_override`    |
| `get_openai_client()` (global singleton)      | `llm_manager.get_provider(tenant_id)`        |

---

## Cost Attribution Per Tenant Per Provider

### Usage Tracking

The existing `LLMUsageTracker` (app/modules/analytics/llm_usage_tracker.py) already tracks token usage. Extend it with provider and tenant context:

```python
async def track_llm_usage(
    tenant_id: str,              # NEW
    provider_id: str,            # NEW: platform or BYOLLM provider
    provider_type: str,          # NEW: "azure_openai", "openai", etc.
    is_byollm: bool,            # NEW: tenant's own key vs platform key
    user_id: str,
    conversation_id: str,
    operation: str,              # "chat_response", "intent_detection", etc.
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
):
    """Track LLM usage with tenant and provider context."""
    # Calculate cost using provider's pricing
    pricing = await get_provider_pricing(provider_id)
    cost = calculate_cost(operation, input_tokens, output_tokens, pricing)

    event = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "provider_id": provider_id,
        "provider_type": provider_type,
        "is_byollm": is_byollm,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "operation": operation,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "latency_ms": latency_ms,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    await usage_container.create_item(event)
```

### Billing Aggregation

```python
# Monthly cost per tenant per provider
SELECT
    c.tenant_id,
    c.provider_type,
    c.is_byollm,
    SUM(c.input_tokens) AS total_input_tokens,
    SUM(c.output_tokens) AS total_output_tokens,
    SUM(c.cost_usd) AS total_cost_usd,
    COUNT(1) AS request_count
FROM usage_events c
WHERE c.timestamp >= @period_start AND c.timestamp < @period_end
GROUP BY c.tenant_id, c.provider_type, c.is_byollm
```

---

## Embedding Provider Strategy

Not all providers offer embedding APIs. The platform must handle this:

| Provider      | Has Embedding API | Fallback                               |
| ------------- | ----------------- | -------------------------------------- |
| Azure OpenAI  | Yes               | N/A                                    |
| OpenAI Direct | Yes               | N/A                                    |
| Anthropic     | No                | Use platform Azure OpenAI or Voyage AI |
| Deepseek      | Yes               | N/A                                    |
| DashScope     | Yes               | N/A                                    |
| Doubao        | Yes               | N/A                                    |
| Gemini        | Yes               | N/A                                    |

### Embedding Provider Separation

```python
# Tenant can use different providers for chat vs embedding
"llm_config": {
    "primary_provider_id": "anthropic-provider-uuid",     # Chat: Claude
    "embedding_provider_id": "azure-openai-provider-uuid", # Embeddings: Azure
}
```

This ensures tenants using Anthropic for chat still get proper embeddings through a provider that supports them.

---

## Plan Tier Provider Access

From `01-admin-hierarchy.md:447-459`:

| Feature                     | Starter      | Professional      | Enterprise         |
| --------------------------- | ------------ | ----------------- | ------------------ |
| Platform default provider   | Yes (1 only) | Yes (all enabled) | Yes (all enabled)  |
| Provider selection          | No           | Yes               | Yes                |
| BYOLLM                      | No           | Yes               | Yes                |
| Custom reasoning_effort     | No           | Yes               | Yes                |
| Provider fallback           | No           | Automatic         | Automatic + custom |
| Usage analytics by provider | Basic        | Detailed          | Detailed + export  |

---

## 80/15/5 Applied to LLM Provider Management

### 80% — Platform-Built (Reusable Across All Tenants)

- LLM provider abstraction layer (unified interface across 7 providers)
- Platform LLM Library: curated, approved providers and models per plan tier
- Provider health monitoring, failover, and circuit breaker logic
- Token tracking and cost attribution engine
- Embedding provider strategy (platform-managed embedding models)
- Reasoning effort routing per provider
- LLM Client Manager with per-request tenant resolution
- `@lru_cache` replacement with Redis-cached tenant config

### 15% — Tenant-Configurable (Self-Service via Admin UI)

- LLM selection from Platform LLM Library (tenant admin picks provider + model)
- Custom reasoning effort per use case (chat, intent, embedding)
- Provider fallback preferences (automatic or custom priority order)
- Usage analytics by provider (view token consumption, cost breakdown)
- Per-use-case model assignment (reasoning-class for complex queries, standard for simple)

### 5% — Custom / Extension (Enterprise Plan)

- BYOLLM: tenant provides own API key and endpoint for any supported provider
- Custom provider integration for providers not in the platform library
- Custom embedding models or fine-tuned model endpoints
- Custom cost attribution rules for BYOLLM tenants (observability-only billing)

---

**Document Version**: 1.1
**Last Updated**: March 4, 2026
