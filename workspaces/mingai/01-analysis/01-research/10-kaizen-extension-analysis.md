# Kaizen AI Providers & LLM Configuration Deep-Dive Analysis

**Document Version**: 1.0
**Date**: 2026-03-04
**Scope**: mingai LLM provider implementation, MCP server integrations, configuration loading, and multi-tenant extension architecture

---

## Executive Summary

**Current State:**

- **Single LLM Provider**: Only Azure OpenAI is currently integrated
- **Configuration Method**: Environment variables only (no database-driven configuration)
- **Multi-Deployment Support**: 4 separate Azure OpenAI deployments (primary chat, auxiliary/intent, document embeddings, KB embeddings, intent detection)
- **9 MCP Servers**: External data integrations including Bloomberg, Perplexity, Azure AD, and others
- **Configuration Per-Service**: Each MCP server has independent credentials/configuration

**Key Findings:**

1. Azure OpenAI is the only implemented LLM provider (hardcoded in openai_client.py)
2. All other providers (OpenAI, Claude/Anthropic, Deepseek, Alibaba Qwen, Bytedance Doubao, Google Gemini) are **missing**
3. Configuration is **environment-variable-driven** only - no database support for multi-tenant provider selection
4. Each MCP server independently manages Azure OpenAI credentials for agentic operations
5. Platform admin can configure LLM parameters (deployments, reasoning effort) but cannot change providers without code changes

---

## Part 1: Currently Implemented Kaizen AI Providers

### 1.1 Azure OpenAI (ONLY Provider)

**Status**: ✅ Fully Implemented
**Location**: `/Users/wailuen/Development/aihub2/src/backend/shared/aihub_shared/services/openai_client.py`

**Key Implementation Details:**

| Aspect              | Details                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| **Client Type**     | `AsyncAzureOpenAI` (async-first for high concurrency)                   |
| **Deployments**     | 4 independent deployments                                               |
| **HTTP Pooling**    | Connection pooling: 100 max connections, 20 keepalive (lines 25-31)     |
| **Timeout Config**  | 120s read timeout for streaming (line 35), suitable for complex queries |
| **Factory Pattern** | `OpenAIClientFactory` manages 4 separate clients (lines 178-394)        |

**Supported Deployments:**

```python
# Primary Chat (line 139)
azure_openai_primary_deployment = "mingai-main"  # GPT-5.2-chat or equivalent

# Auxiliary/Intent Detection (line 140)
azure_openai_auxiliary_deployment = "intent5"    # GPT-5-mini

# Document Embeddings (line 141)
azure_openai_doc_embedding_deployment = "text-embedding-3-large"

# KB Embeddings (line 147)
azure_openai_kb_embedding_deployment = "text-embedding-ada-002"

# Intent Detection Separate (line 151)
azure_openai_intent_deployment = "intent5"
```

**Configuration Loading:**

All configuration comes from environment variables via `Settings` class (config.py lines 13-495):

```python
# From /Users/wailuen/Development/aihub2/src/backend/api-service/app/core/config.py

# Primary Endpoint (lines 83-88)
azure_openai_endpoint: str = Field(default="")
azure_openai_key: str = Field(default="")
azure_openai_api_version: str = Field(default="2024-12-01-preview")
azure_openai_primary_deployment: str = Field(default="mingai-main")
azure_openai_auxiliary_deployment: str = Field(default="intent5")

# KB Endpoint (Secondary - lines 174-176)
azure_openai_kb_endpoint: str = Field(default="")
azure_openai_kb_key: str = Field(default="")
azure_openai_kb_embedding_deployment: str = Field(default="text-embedding-ada-002")

# Intent Detection Separate Endpoint (lines 127-151)
azure_openai_intent_endpoint: str = Field(default="")
azure_openai_intent_api_key: str = Field(default="")
azure_openai_intent_deployment: str = Field(default="intent5")
azure_openai_intent_reasoning_effort: str = Field(default="none")

# Chat Reasoning Effort (line 167-171)
azure_openai_chat_reasoning_effort: str = Field(default="none")
```

**Deployment Model:**

```
┌─────────────────────────────────────────────────────┐
│         Primary Azure OpenAI Resource               │
│  (uses AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY)   │
├─────────────────────────────────────────────────────┤
│ ├─ mingai-main (GPT-5.2-chat)          [PRIMARY]   │
│ ├─ intent5 (GPT-5-mini)                 [AUXILIARY] │
│ └─ text-embedding-3-large (embeddings)  [DOCS]     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│    Secondary KB Resource (Optional)                  │
│  (uses AZURE_OPENAI_KB_ENDPOINT + KEY, fallback)   │
├─────────────────────────────────────────────────────┤
│ └─ text-embedding-ada-002 (KB embeddings) [KB]     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│   Intent Detection Resource (Optional)              │
│ (uses AZURE_OPENAI_INTENT_ENDPOINT + KEY)          │
├─────────────────────────────────────────────────────┤
│ └─ intent5 (GPT-5-mini for intent) [INTENT]        │
└─────────────────────────────────────────────────────┘
```

**Reasoning Effort Support:**

- Intent detection reasoning effort: `"none" | "low" | "medium" | "high"` (line 147)
- Chat response reasoning effort: `"none" | "low" | "medium" | "high"` (line 167)
- Values read from environment at startup, cannot change per-request

**Client Access Pattern:**

```python
# From openai_client.py lines 178-394
factory = OpenAIClientFactory(config)

# Get client instances
client = factory.get_openai_client()                    # Primary
kb_client = factory.get_kb_openai_client()             # KB (fallback to primary if unconfigured)
doc_client = factory.get_doc_openai_client()           # Doc embeddings (fallback to primary)
intent_client = factory.get_intent_openai_client()     # Intent detection (fallback to primary)

# Get deployment names
primary_deployment = factory.get_primary_deployment()
doc_embedding_deployment = factory.get_doc_embedding_deployment()
intent_deployment = factory.get_intent_deployment()
```

---

## Part 2: Missing AI Providers (NOT Implemented)

### Status: ❌ ZERO Additional Providers Integrated

The following providers are **completely absent** from the codebase:

| Provider                        | Status     | Rationale                                                                   |
| ------------------------------- | ---------- | --------------------------------------------------------------------------- |
| **OpenAI** (GPT-4, GPT-5, etc.) | ❌ Missing | Only Azure OpenAI SDK (`AsyncAzureOpenAI`) is used                          |
| **Claude/Anthropic**            | ❌ Missing | No Anthropic SDK import or configuration                                    |
| **Deepseek**                    | ❌ Missing | No Deepseek SDK or API client                                               |
| **Alibaba Qwen**                | ❌ Missing | No Alibaba SDK integration                                                  |
| **Bytedance Doubao**            | ❌ Missing | No Bytedance/BytePlus SDK                                                   |
| **Google Gemini**               | ❌ Missing | No Google AI SDK (though Azure AI Search uses embedding-3-large from Azure) |

**Evidence:**

1. **openai_client.py** (lines 1-464): Only imports Azure OpenAI SDK

   ```python
   from openai import AsyncAzureOpenAI  # Line 20 - ONLY LLM import
   ```

2. **config.py** (lines 1-496): Only Azure OpenAI configuration fields, no provider abstraction

   ```python
   # Only Azure OpenAI settings, no factory for other providers
   azure_openai_endpoint: str
   azure_openai_key: str
   azure_openai_primary_deployment: str
   # ... (no openai_, claude_, deepseek_, qwen_, doubao_, gemini_ fields)
   ```

3. **main.py** (lines 1-150+): Service initialization only bootstraps Azure OpenAI

   ```python
   # Line 22: from app.core.config import settings
   # NO conditional imports for other LLM providers
   ```

4. **Grep Results**: No references to other LLM SDKs in codebase
   ```
   ❌ No "from anthropic import"
   ❌ No "import openai" (non-Azure)
   ❌ No "deepseek" package references
   ❌ No "alibaba" or "qwen" references
   ❌ No "bytedance" or "doubao" references
   ❌ No "google.generativeai" or "gemini" SDK
   ```

---

## Part 3: MCP Server Implementations & External API Dependencies

### 3.1 MCP Server Overview

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/`
**Total Count**: 10 servers
**All Servers**: azure-ad, alphageo, bloomberg, capiq, ilevel, oracle-fusion, perplexity, pitchbook, teamworks

### 3.2 MCP Server Details with External API & Credential Requirements

#### **1. Azure AD MCP** ⭐ (Cloud, Internal)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/azure-ad-mcp/app/config.py`

**External APIs Called:**

- Microsoft Graph API v1.0 (https://graph.microsoft.com/v1.0) - lines 30
- Azure AD OAuth2 endpoint - line 67 (Redis token cache for OBO)

**Required Credentials** (lines 17-19):

```python
AZURE_TENANT_ID: str          # Required
AZURE_CLIENT_ID: str          # Required (must differ from mingai app)
AZURE_CLIENT_SECRET: str      # Required
```

**LLM Integration**:

- Azure OpenAI for agentic orchestration (lines 61-63)
- Deployment: "mcp-azuread" (separate from main service)
- Optional: Can fall back if not configured

**Scopes Requested** (lines 33-55):

- User.Read.All, Mail.Read/Write/Send, Calendars.Read/Write
- Chat.Read/Write, Teams/Channels/Channel Messages
- Files.Read.All (OneDrive/SharePoint), Places.Read.All
- OnlineMeetings.ReadWrite, OnlineMeetingTranscript.Read.All
- People.Read, Contacts.ReadWrite

**Stateful Features** (lines 112-124):

- Agent communications (email sending, calendar creation) - requires SHARED_MAILBOX_ADDRESS
- Smart scheduling with availability checks
- Multi-participant coordination with LLM reasoning

**Infrastructure Dependencies**:

- Redis (optional, for MSAL token cache - line 67)
- CosmosDB (for webhook persistence - lines 90-91)

---

#### **2. Bloomberg MCP** 💹 (Proprietary, Market Data)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/bloomberg-mcp/app/config.py`

**External APIs Called:**

- Bloomberg DL API (https://api.bloomberg.com/eap) - line 29
- Bloomberg OAuth2 token endpoint (https://bsso.blpprofessional.com/ext/api/as/token.oauth2) - line 30

**Required Credentials** (lines 24-26):

```python
BLOOMBERG_CLIENT_ID: str      # Required (DL account app ID)
BLOOMBERG_CLIENT_SECRET: str  # Required
BLOOMBERG_ACCOUNT: str = "794318"  # DL account/catalog ID (default provided)
```

**LLM Integration**:

- Azure OpenAI for tool outputs/analysis (lines 41-43)
- Deployment: "mcp-bloomberg" (separate from main service)
- Optional: Has_azure_openai property to check if configured

**Rate Limiting** (lines 33-34):

```python
RATE_LIMIT_REQUESTS: int = 100
RATE_LIMIT_WINDOW: int = 60  # seconds
```

**Caching** (lines 37-38):

```python
CACHE_TTL: int = 300          # 5 minutes for market data
CACHE_TTL_STATIC: int = 86400 # 24 hours for static data
```

**Available Tools** (from main.py - too large to show):

- Market data queries
- Fundamental analysis
- Historical price data
- FX rates
- Company comparables
- Research reports

---

#### **3. Perplexity MCP** 🔍 (Internet Search, Research)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/perplexity-mcp/app/config.py`

**External APIs Called:**

- Perplexity API (https://api.perplexity.ai) - line 18

**Required Credentials** (lines 17):

```python
PERPLEXITY_API_KEY: str = ""  # Required (Tier 2+ for images)
```

**LLM Models Supported** (lines 24-26):

```python
PERPLEXITY_MODEL_FAST: str = "sonar"              # Quick searches (1200 tok/s, $1/1M input)
PERPLEXITY_MODEL_RESEARCH: str = "sonar-pro"     # Deep research (2x citations, $3/1M input)
PERPLEXITY_MODEL_REASONING: str = "sonar-reasoning"  # Multi-step analysis ($1/1M input)
```

**LLM Integration**:

- Azure OpenAI for agentic orchestration of Perplexity calls (lines 43-47)
- Deployment: "mcp-perplexity" (separate from main service)
- Reasoning effort support: "none", "low", "medium", "high" (line 47)

**Rate Limiting** (lines 30-32):

```python
RATE_LIMIT_REQUESTS: int = 50
RATE_LIMIT_WINDOW: int = 60    # seconds
RATE_LIMIT_ADAPTIVE: bool = True  # Respects 429 Retry-After
```

**Caching** (lines 35-37):

```python
CACHE_TTL_NEWS: int = 300      # 5 minutes (news freshness)
CACHE_TTL_RESEARCH: int = 3600 # 1 hour (stable research content)
CACHE_MAX_SIZE: int = 500      # entries
```

**Image Handling** (line 58):

```python
RETURN_IMAGES_DEFAULT: bool = True  # Enable by default
```

---

#### **4. CapIQ MCP** 📊 (S&P Capital IQ, Company Data)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/capiq-mcp/app/`

**External APIs Called:**

- S&P Capital IQ API

**Required Credentials**:

- CapIQ API key (likely S&P/Refinitiv credentials)

**Status**: Not fully examined, but follows same pattern as Bloomberg/Perplexity

---

#### **5. iLevel MCP** 🏢 (Enterprise Data)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/ilevel-mcp/app/`

**External APIs Called:**

- iLevel proprietary API

**Required Credentials**:

- iLevel API credentials

**Status**: Not fully examined, proprietary integration

---

#### **6. Oracle Fusion MCP** 🗄️ (ERP System)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/oracle-fusion-mcp/app/`

**External APIs Called:**

- Oracle Fusion Cloud API (REST endpoints)

**Required Credentials**:

- Oracle tenant URL
- OAuth2 credentials or API tokens

**Status**: Not fully examined, enterprise ERP integration

---

#### **7. PitchBook MCP** 📈 (PE/VC Data)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/pitchbook-mcp/app/`

**External APIs Called:**

- PitchBook API (Morningstar)

**Required Credentials**:

- PitchBook API key

**Status**: Not fully examined, VC/PE data integration

---

#### **8. Teamworks MCP** 👥 (Collaboration)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/teamworks-mcp/app/`

**External APIs Called:**

- Teamworks API (likely internal collaboration platform)

**Required Credentials**:

- Teamworks API credentials

**Status**: Not fully examined

---

#### **9. AlphaGeo MCP** 🌍 (Location/Geographic Data)

**Location**: `/Users/wailuen/Development/aihub2/src/mcp-servers/alphageo-mcp/app/`

**External APIs Called:**

- AlphaGeo API (geographic data provider)

**Required Credentials**:

- AlphaGeo API key

**Status**: Not fully examined

---

### 3.3 MCP Server Credential Management Pattern

**All servers follow the same pattern:**

1. **Environment Variable Loading**:

   ```python
   # Each server's config.py uses pydantic-settings
   class Settings(BaseSettings):
       model_config = SettingsConfigDict(
           env_file=".env",
           env_file_encoding="utf-8",
           case_sensitive=False,
       )

       PROVIDER_API_KEY: str        # Required
       PROVIDER_CLIENT_ID: str      # If OAuth
       PROVIDER_CLIENT_SECRET: str  # If OAuth
   ```

2. **Per-Server Azure OpenAI Configuration**:
   - Most servers have optional Azure OpenAI settings for agentic orchestration
   - Deployment name is MCP-specific (e.g., "mcp-bloomberg", "mcp-perplexity")
   - Falls back gracefully if not configured

3. **No Central Credential Management**:
   - Each server loads credentials independently from .env
   - No shared credential store (except Azure KeyVault mention in comments)
   - No per-tenant credential isolation

---

## Part 4: Current LLM Configuration Loading Mechanism

### 4.1 How LLM Config Currently Gets Loaded

**Architecture**: **Environment Variables Only** ❌ No Database Support

**Startup Flow**:

````
1. Service starts (main.py line 104)
   ↓
2. Pydantic BaseSettings loads from .env (config.py line 484)
   ├─ env_file = ".env"
   ├─ case_sensitive = False
   └─ extra = "ignore"
   ↓
3. Settings singleton created (config.py lines 489-495)
   ```python
   @lru_cache
   def get_settings() -> Settings:
       return Settings()  # Loads from .env once, cached

   settings = get_settings()
````

↓ 4. API-Service Initialization (main.py line 22)
├─ from app.core.config import settings
├─ All Azure OpenAI vars read at import time
└─ NO conditional logic for other providers
↓ 5. OpenAI Client Factory Created
├─ config = create_openai_client_config_from_settings(settings)
├─ factory = OpenAIClientFactory(config)
└─ Clients cached (not re-created per request)
↓ 6. Hard-coded to use AsyncAzureOpenAI
└─ NO runtime provider switching capability

````

**Configuration Sources** (in order):

1. **Environment Variables** (primary)
   - `AZURE_OPENAI_ENDPOINT`
   - `AZURE_OPENAI_KEY`
   - `AZURE_OPENAI_PRIMARY_DEPLOYMENT`
   - `AZURE_OPENAI_AUXILIARY_DEPLOYMENT`
   - etc. (see Part 1 for full list)

2. **Hardcoded Defaults** (fallback)
   - API version: `"2024-12-01-preview"` (config.py line 85)
   - Primary deployment: `"mingai-main"` (config.py line 87)
   - Auxiliary deployment: `"intent5"` (config.py line 91)
   - KB embedding: `"text-embedding-ada-002"` (config.py line 176)

3. **NO Database Support**
   - Settings object is read-only at runtime
   - Cannot modify configuration without restarting service
   - No multi-tenant provider selection capability

### 4.2 Current Configuration Immutability

```python
# From config.py - Settings is loaded once at startup

@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # Called once, result cached forever

settings = get_settings()  # Global singleton

# Later in application:
# settings.azure_openai_endpoint  <- CANNOT change at runtime
# settings.azure_openai_primary_deployment  <- CANNOT change per-tenant
````

**Key Limitations:**

1. Configuration is **loaded at startup only**
2. **@lru_cache prevents re-reading .env** (even if updated)
3. **No database-driven configuration** means each environment needs separate .env file
4. **Hard-coded to Azure OpenAI** - no provider selection logic

---

## Part 5: Multi-Tenant LLM Provider Selection Architecture (Proposed)

### 5.1 Current Single-Tenant Model

```
┌─────────────────────────────────────────┐
│      One Azure OpenAI Account           │
│   (per environment: dev/staging/prod)   │
├─────────────────────────────────────────┤
│  All Tenants ──→ Same Deployments       │
│  ├─ mingai-main (all tenants use)       │
│  ├─ intent5 (all tenants use)           │
│  └─ embeddings (all tenants use)        │
└─────────────────────────────────────────┘
```

**Problem**: Cannot charge different providers to different tenants or allow tenant-specific LLM selection.

### 5.2 Proposed Multi-Tenant Design

**Architecture Overview:**

```
┌──────────────────────────────────────────────────────────────┐
│            Platform Admin Configuration                       │
│  (Manages which LLM providers are available + credentials)    │
├──────────────────────────────────────────────────────────────┤
│  Admin UI / API: /v1/admin/llm-providers                      │
│  ├─ Create Provider Config (Azure OpenAI, OpenAI, Claude...) │
│  ├─ Add Credentials (API keys, endpoints)                    │
│  ├─ Set Default Provider                                     │
│  └─ Enable/Disable Per-Provider                              │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│         LLM Provider Registry (Database)                      │
│  Table: llm_providers                                         │
│  ├─ provider_id (UUID)                                       │
│  ├─ provider_name (azure_openai, openai, claude, etc.)      │
│  ├─ endpoint_url                                             │
│  ├─ api_key (encrypted)                                      │
│  ├─ configuration (JSON: deployments, reasoning_effort)      │
│  ├─ is_enabled (bool)                                        │
│  └─ updated_at (timestamp)                                   │
│                                                               │
│  Table: tenant_llm_settings                                  │
│  ├─ tenant_id (UUID)                                         │
│  ├─ preferred_llm_provider_id (UUID, FK)                    │
│  ├─ can_select_alternative_providers (bool)                  │
│  └─ updated_at (timestamp)                                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│        Tenant-Side Configuration                              │
│  (Tenant selects which provider to use for their tenancy)     │
├──────────────────────────────────────────────────────────────┤
│  UI: Settings → LLM Provider Selection                        │
│  ├─ Default Provider (set by admin)                           │
│  ├─ Available Alternatives (if enabled by admin)             │
│  └─ Per-User Preference Override (optional)                  │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│        LLM Client Factory (Runtime)                           │
│  LLMClientFactory                                             │
│  ├─ get_client(tenant_id, use_case: "chat" | "embedding")   │
│  │  ├─ Query provider registry for tenant's LLM              │
│  │  ├─ Load credentials from encrypted storage               │
│  │  └─ Instantiate appropriate SDK (Azure, OpenAI, Claude..) │
│  │                                                            │
│  ├─ get_deployment(provider, use_case) → str               │
│  │  ├─ Maps use case to provider-specific deployment name    │
│  │  └─ Returns correct model name (varies by provider)       │
│  │                                                            │
│  └─ CLIENTS CACHED PER TENANT (not global)                  │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│     Chat Endpoint (Per-Request)                               │
│  POST /v1/conversations/chat                                  │
│  ├─ Extract tenant from JWT (from auth middleware)            │
│  ├─ Get LLM client for this tenant                           │
│  │  (via LLMClientFactory.get_client(tenant_id))             │
│  └─ Stream response using tenant-specific provider            │
└──────────────────────────────────────────────────────────────┘
```

### 5.3 Required Code Changes (Implementation Plan)

#### **Phase 1: Database Schema**

```sql
-- Admin-managed provider configurations
CREATE TABLE llm_providers (
    id UUID PRIMARY KEY,
    provider_type VARCHAR(50) NOT NULL,  -- 'azure_openai', 'openai', 'claude', 'deepseek', etc.
    display_name VARCHAR(255) NOT NULL,
    endpoint_url VARCHAR(2048) NOT NULL,
    api_key_encrypted VARBINARY NOT NULL,  -- Encrypted at rest
    configuration NVARCHAR(MAX) NOT NULL,   -- JSON: {"deployment":"...", "reasoning_effort":"..."}
    is_enabled BOOLEAN DEFAULT true,
    created_at DATETIME DEFAULT GETUTCDATE(),
    updated_at DATETIME DEFAULT GETUTCDATE(),
    created_by_user_id UUID,
    UNIQUE(provider_type)
);

-- Tenant's LLM preferences
CREATE TABLE tenant_llm_settings (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL UNIQUE,
    preferred_llm_provider_id UUID NOT NULL,
    allow_tenant_override BOOLEAN DEFAULT false,
    updated_at DATETIME DEFAULT GETUTCDATE(),
    FOREIGN KEY (preferred_llm_provider_id) REFERENCES llm_providers(id)
);

-- Per-conversation provider selection (optional)
CREATE TABLE conversation_llm_settings (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL UNIQUE,
    tenant_id UUID NOT NULL,
    llm_provider_id UUID NOT NULL,  -- Provider chosen for this conversation
    updated_at DATETIME DEFAULT GETUTCDATE(),
    FOREIGN KEY (llm_provider_id) REFERENCES llm_providers(id)
);
```

#### **Phase 2: LLM Client Factory (New)**

**File**: `src/backend/shared/mingai_shared/services/llm_client_factory.py`

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict
from dataclasses import dataclass
import json

@dataclass
class LLMProviderConfig:
    """Abstract LLM provider configuration."""
    provider_type: str
    endpoint: str
    api_key: str
    configuration: Dict  # JSON: {"deployment": "...", "reasoning_effort": "..."}

class LLMClientFactory(ABC):
    """Abstract factory for creating LLM clients."""

    @abstractmethod
    def get_client(self, config: LLMProviderConfig):
        """Get configured LLM client."""
        pass

    @abstractmethod
    def get_deployment_name(self, use_case: str) -> str:
        """Get provider-specific deployment/model name for use case."""
        pass

class AzureOpenAIClientFactory(LLMClientFactory):
    """Creates AsyncAzureOpenAI clients (current implementation)."""

    def get_client(self, config: LLMProviderConfig):
        # Uses existing OpenAIClientFactory
        return AsyncAzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.configuration.get("api_version", "2024-12-01-preview"),
        )

    def get_deployment_name(self, use_case: str) -> str:
        # Maps use_case -> deployment name
        deployments = {
            "chat": self.config.get("primary_deployment", "mingai-main"),
            "intent": self.config.get("intent_deployment", "intent5"),
            "embedding": self.config.get("embedding_deployment", "text-embedding-3-large"),
        }
        return deployments.get(use_case)

class OpenAIClientFactory(LLMClientFactory):
    """Creates OpenAI SDK clients (for openai.com)."""

    def get_client(self, config: LLMProviderConfig):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=config.api_key)

    def get_deployment_name(self, use_case: str) -> str:
        deployments = {
            "chat": "gpt-4-turbo",
            "intent": "gpt-4-mini",
            "embedding": "text-embedding-3-large",
        }
        return deployments.get(use_case)

class AnthropicClientFactory(LLMClientFactory):
    """Creates Anthropic SDK clients (Claude)."""

    def get_client(self, config: LLMProviderConfig):
        from anthropic import Anthropic
        return Anthropic(api_key=config.api_key)

    def get_deployment_name(self, use_case: str) -> str:
        deployments = {
            "chat": "claude-opus-4-1",
            "intent": "claude-haiku-3-5",
            "embedding": "claude-embedding",  # Hypothetical
        }
        return deployments.get(use_case)

class LLMClientManager:
    """Manages LLM client creation per tenant."""

    def __init__(self, db_service, encryption_service):
        self.db_service = db_service
        self.encryption_service = encryption_service
        self._client_cache: Dict[str, LLMClientFactory] = {}  # tenant_id -> factory

        self.factories = {
            "azure_openai": AzureOpenAIClientFactory,
            "openai": OpenAIClientFactory,
            "claude": AnthropicClientFactory,
            # Add more as providers are integrated
        }

    async def get_client_for_tenant(self, tenant_id: str, use_case: str = "chat"):
        """Get LLM client for tenant's configured provider."""

        # Get tenant's LLM settings
        tenant_settings = await self.db_service.get_tenant_llm_settings(tenant_id)

        # Get provider configuration
        provider_config = await self.db_service.get_provider_config(
            tenant_settings.preferred_llm_provider_id
        )

        # Decrypt API key
        decrypted_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Get appropriate factory
        factory_class = self.factories.get(provider_config.provider_type)
        factory = factory_class(json.loads(provider_config.configuration))

        # Create and cache client
        client_key = f"{tenant_id}:{provider_config.provider_type}"
        if client_key not in self._client_cache:
            config = LLMProviderConfig(
                provider_type=provider_config.provider_type,
                endpoint=provider_config.endpoint_url,
                api_key=decrypted_key,
                configuration=json.loads(provider_config.configuration),
            )
            self._client_cache[client_key] = factory.get_client(config)

        return self._client_cache[client_key]

    def get_deployment_for_tenant(self, tenant_id: str, use_case: str) -> str:
        """Get deployment/model name for tenant's provider."""
        # Similar logic to get_client_for_tenant
        pass
```

#### **Phase 3: Admin API Endpoints**

**File**: `src/backend/api-service/app/modules/admin/llm_providers_router.py`

```python
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admin/llm-providers", tags=["admin"])

class LLMProviderRequest(BaseModel):
    provider_type: str  # 'azure_openai', 'openai', 'claude', etc.
    endpoint_url: str
    api_key: str
    configuration: dict  # {"deployment": "...", ...}
    is_enabled: bool = True

@router.post("/")
async def create_llm_provider(req: LLMProviderRequest, current_user = Depends(require_admin)):
    """Create a new LLM provider configuration."""
    # Validate provider_type is supported
    # Encrypt API key
    # Store in database
    pass

@router.get("/")
async def list_llm_providers(current_user = Depends(require_admin)):
    """List all configured LLM providers (keys redacted)."""
    pass

@router.put("/{provider_id}")
async def update_llm_provider(provider_id: str, req: LLMProviderRequest, ...):
    """Update provider configuration and credentials."""
    pass

@router.post("/{provider_id}/test")
async def test_llm_provider(provider_id: str, current_user = Depends(require_admin)):
    """Test provider connectivity with a simple API call."""
    pass

@router.delete("/{provider_id}")
async def delete_llm_provider(provider_id: str, current_user = Depends(require_admin)):
    """Delete provider (only if not in use)."""
    pass
```

#### **Phase 4: Tenant Settings UI / API**

**File**: `src/backend/api-service/app/modules/settings/llm_router.py`

```python
@router.get("/v1/tenant/llm-settings")
async def get_tenant_llm_settings(current_user = Depends(get_current_user)):
    """Get tenant's LLM provider selection."""
    tenant_id = current_user.tenant_id
    settings = await db.get_tenant_llm_settings(tenant_id)

    # Return available providers + current selection
    available_providers = await db.list_enabled_providers()
    return {
        "preferred_provider_id": settings.preferred_llm_provider_id,
        "available_providers": [
            {
                "provider_id": p.id,
                "provider_type": p.provider_type,
                "display_name": p.display_name,
            }
            for p in available_providers if p.is_enabled
        ],
    }

@router.put("/v1/tenant/llm-settings")
async def update_tenant_llm_settings(
    req: {"preferred_provider_id": str},
    current_user = Depends(require_tenant_admin)
):
    """Tenant selects preferred LLM provider."""
    # Update tenant_llm_settings table
    pass
```

#### **Phase 5: Chat Endpoint Modification**

**File**: `src/backend/api-service/app/modules/chat/router.py` (existing, modify lines ~100)

**Current Code** (lines ~100-120):

```python
@router.post("/v1/conversations/{conversation_id}/messages")
async def chat(conversation_id: str, req: ChatRequest, current_user = Depends(get_current_user)):
    # Currently hardcoded to use Azure OpenAI
    openai_client = factory.get_openai_client()  # Global factory
    deployment = factory.get_primary_deployment()  # Hard-coded
```

**New Code** (Multi-tenant aware):

```python
@router.post("/v1/conversations/{conversation_id}/messages")
async def chat(conversation_id: str, req: ChatRequest, current_user = Depends(get_current_user)):
    tenant_id = current_user.tenant_id

    # Get LLM client for this tenant's configured provider
    client = await llm_client_manager.get_client_for_tenant(tenant_id, use_case="chat")
    deployment = await llm_client_manager.get_deployment_for_tenant(tenant_id, use_case="chat")

    # Provider-specific client handling
    if isinstance(client, AsyncAzureOpenAI):
        response = await client.chat.completions.create(
            deployment_id=deployment,
            messages=req.messages,
            # ...
        )
    elif isinstance(client, AsyncOpenAI):
        response = await client.chat.completions.create(
            model=deployment,  # OpenAI uses "model" not "deployment_id"
            messages=req.messages,
            # ...
        )
    elif isinstance(client, Anthropic):
        response = await client.messages.create(
            model=deployment,
            messages=req.messages,
            # ...
        )
```

### 5.4 Tenant Admin Flow (UX)

```
Tenant Admin logs in
         ↓
Settings → LLM Provider
         ↓
Display:
├─ "Default Provider: Azure OpenAI" (set by platform admin)
├─ "Available Alternative Providers:"
│  ├─ ☑ OpenAI GPT-4 Turbo
│  ├─ ☑ Claude Opus 4.1
│  └─ ☐ Deepseek (not yet enabled by platform)
│
Click "Select OpenAI GPT-4"
         ↓
Save preference to database
         ↓
Next conversation uses OpenAI
```

### 5.5 Multi-Tenant Cost Attribution

```
┌─────────────────────────────────────┐
│  Each API call logs:                 │
│  ├─ tenant_id                        │
│  ├─ llm_provider_id                  │
│  ├─ input_tokens                     │
│  ├─ output_tokens                    │
│  ├─ timestamp                        │
│  └─ cost_calculated (using provider- │
│      specific pricing)                │
└─────────────────────────────────────┘
         ↓
   Monthly Report:
   Tenant A ← OpenAI @ $0.005/1k input
   Tenant B ← Claude @ $0.003/1k input
   Tenant C ← Azure OpenAI @ $0.002/1k input
```

---

## Part 6: Implementation Roadmap

### Phase 1: Database & Infrastructure (Week 1-2)

- [ ] Create llm_providers + tenant_llm_settings tables
- [ ] Implement encryption service for API keys (AES-256)
- [ ] Set up initial Azure OpenAI provider config record

### Phase 2: LLM Client Factory (Week 2-3)

- [ ] Create abstract LLMClientFactory base class
- [ ] Implement AzureOpenAIClientFactory (existing code)
- [ ] Implement OpenAIClientFactory (new)
- [ ] Implement AnthropicClientFactory (new - Claude)

### Phase 3: Admin APIs (Week 3-4)

- [ ] /v1/admin/llm-providers CRUD endpoints
- [ ] Provider testing endpoint
- [ ] Provider credential validation

### Phase 4: Tenant APIs (Week 4-5)

- [ ] /v1/tenant/llm-settings GET/PUT
- [ ] Tenant selection logic
- [ ] Frontend integration for provider selection

### Phase 5: Chat Integration (Week 5-6)

- [ ] Modify chat endpoint to use LLMClientManager
- [ ] Handle per-provider request formatting differences
- [ ] Provider-specific response parsing

### Phase 6: Cost Attribution & Monitoring (Week 6-7)

- [ ] Log usage per provider + tenant
- [ ] Create usage analytics tables
- [ ] Monthly billing report generation

### Phase 7: Additional Providers (Week 7+)

- [ ] Deepseek provider integration
- [ ] Alibaba Qwen provider integration
- [ ] Bytedance Doubao provider integration
- [ ] Google Gemini provider integration

---

## Part 7: Key Findings & Recommendations

### 7.1 Current State Summary

| Aspect                     | Status                             | Evidence                               |
| -------------------------- | ---------------------------------- | -------------------------------------- |
| **Single Provider**        | ✅ Implemented (Azure OpenAI only) | openai_client.py, config.py            |
| **Multi-Provider Support** | ❌ Absent                          | Zero abstraction, hardcoded SDK        |
| **Config Loading**         | ✅ Environment Variables           | Pydantic BaseSettings, .env file       |
| **Database Config**        | ❌ Not Implemented                 | No schema for provider management      |
| **Per-Tenant Selection**   | ❌ Not Possible                    | No tenant_llm_settings concept         |
| **Credential Management**  | ⚠️ Partially (MCP only)            | Each MCP server loads independently    |
| **Multi-Deployment**       | ✅ Yes (4 Azure deployments)       | Primary, auxiliary, embeddings, intent |

### 7.2 Critical Gaps

1. **No Provider Abstraction**: Switching providers requires code changes
2. **No Multi-Tenant Awareness**: Configuration is global (all tenants use same provider)
3. **No Encryption for Credentials**: API keys stored in plain text in .env
4. **No Runtime Credential Changes**: Service restart required for config updates
5. **No Provider Fallback Logic**: If primary provider fails, no automatic switch
6. **No Cost Attribution**: Cannot charge different tenants different providers

### 7.3 Recommended Next Steps

**Immediate (1-2 weeks)**:

1. Implement provider abstraction layer (LLMClientFactory)
2. Add database schema for llm_providers table
3. Integrate with existing encryption service

**Short-term (1 month)**:

1. Implement OpenAI provider integration
2. Add admin APIs for provider management
3. Implement tenant provider selection

**Medium-term (2-3 months)**:

1. Add Anthropic Claude integration
2. Add Deepseek integration
3. Implement cost attribution + billing

**Long-term (3+ months)**:

1. Add Alibaba Qwen + Bytedance Doubao
2. Add Google Gemini integration
3. Implement provider performance analytics + auto-selection

---

## Appendix: File References & Code Locations

| Component              | File                                                     | Lines  | Details                                     |
| ---------------------- | -------------------------------------------------------- | ------ | ------------------------------------------- |
| Azure OpenAI Client    | `/backend/shared/mingai_shared/services/openai_client.py` | 1-464  | Factory pattern, 4 client managers          |
| Config Settings        | `/backend/api-service/app/core/config.py`                | 13-495 | Pydantic BaseSettings, env variable loading |
| Service Initialization | `/backend/api-service/app/main.py`                       | 1-150+ | Startup bootstrap, no conditional imports   |
| Azure AD MCP Config    | `/mcp-servers/azure-ad-mcp/app/config.py`                | 1-148  | Azure AD + Graph API, LLM orchestration     |
| Bloomberg MCP Config   | `/mcp-servers/bloomberg-mcp/app/config.py`               | 1-72   | Bloomberg DL API, rate limiting, caching    |
| Perplexity MCP Config  | `/mcp-servers/perplexity-mcp/app/config.py`              | 1-68   | Perplexity API, 3 models, caching           |

---

**Document Complete**
Generated: 2026-03-04
Status: Ready for Architecture Review & Implementation Planning
