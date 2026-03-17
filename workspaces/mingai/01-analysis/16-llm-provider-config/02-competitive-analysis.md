# LLM Provider Configuration — Competitive Analysis

**Date**: March 17, 2026
**Status**: Research Complete
**Scope**: How enterprise AI platforms handle multi-provider LLM credential management

---

## Overview

This analysis examines six platforms — three hyperscaler-native and three open-source/commercial — to understand the range of patterns in enterprise LLM provider configuration. The key question is not "what features do they have" but "what credential management model is most enterprise-friendly, and why."

---

## 1. Vertex AI Agent Builder (Google Cloud)

### How it works

Vertex AI Agent Builder does not have a traditional "configure your LLM API key" UI. Instead, it uses **IAM-based identity** as the credential mechanism. Your GCP project identity (service account) is the credential. Google manages the connection to Gemini models through the same IAM trust that governs all GCP resources.

For third-party models, Vertex AI provides a "Model Garden" that includes Anthropic Claude, Meta Llama, Mistral, and others. Access is provisioned through the GCP console — the user grants access to a model from the Garden catalog, and Vertex AI handles the credential exchange behind the scenes (it may use a marketplace agreement plus IAM).

For developers who want to call external LLM APIs from within agent workflows, Vertex AI supports "Secret Manager" integration — you store the API key in GCP Secret Manager and reference it by name in your agent config. The agent runtime resolves the secret at call time.

### Credential management model

- **First-party models**: IAM-gated, no API key management at all
- **Marketplace models (Claude, Llama)**: Marketplace agreement + IAM, one-click enablement
- **External APIs**: Secret Manager reference (key stored in managed secrets infrastructure, not in the agent config directly)
- **Admin UI**: GCP Console → Vertex AI → Model Garden (enable/disable models per project)

### What's notable

The IAM model entirely sidesteps the "where do I store the API key" problem for Google-native resources. The tradeoff is vendor lock-in: this only works if you're all-in on GCP. The Secret Manager integration for external APIs is the closest analogue to mingai's credential store — it's a managed, auditable, access-controlled credential vault that agent infrastructure references by name.

### Gap vs. mingai's requirement

Vertex AI is a single-tenant per GCP project. It does not have a multi-tenant model where one platform serves hundreds of organizations with potentially different provider configurations. The credential management model is designed for a single organization's infra, not for a SaaS platform serving multiple tenants.

---

## 2. Azure AI Foundry (formerly Azure AI Studio)

### How it works

Azure AI Foundry is the closest competitor to mingai's architecture. It serves as both a model catalog and a deployment management platform. Key concepts:

- **Model Catalog**: Browse and deploy models from OpenAI, Meta, Mistral, Cohere, etc. Each model has a published card with capability metadata and pricing.
- **Deployments**: When you deploy a model from the catalog, you create a named endpoint with its own URL and API key. The platform manages the credential.
- **Connections**: AI Foundry has a "Connections" concept — you create a connection to an external resource (Azure OpenAI, another AI service, a custom endpoint) and give it a name. Agent workflows reference the connection name, not the raw credentials.

### Credential management model

- **First-party (Azure OpenAI)**: Managed via Azure RBAC and Managed Identity. No key management needed for same-tenant deployments.
- **External models**: "Connections" UI in AI Foundry — name, URL, API key. Key is stored in Azure Key Vault, referenced by name in the connection config.
- **Audit**: All connection creation/modification events flow to Azure Monitor.
- **Testing**: "Chat playground" in AI Foundry allows testing any connected model before production use.

### What's notable

AI Foundry's "Connections" model is the direct inspiration for what mingai's `llm_providers` table should be. It explicitly separates:

1. The model catalog (what models exist, their capabilities, pricing)
2. The connection configuration (how to reach them — endpoint, credentials)

This two-layer model is exactly what mingai needs to complete. AI Foundry also has the notion of a "default" connection per deployment hub, which maps to mingai's `is_default` flag.

The "Chat playground" testing feature is a direct analogue to mingai's `/platform/providers/{id}/test` endpoint.

### Gap vs. mingai's requirement

AI Foundry is still single-organization (one Azure tenant). The multi-tenant SaaS pattern — where Platform Admin configures providers and Tenant Admins use them — is not native to AI Foundry. You'd have to build that layer yourself.

---

## 3. AWS Bedrock

### How it works

AWS Bedrock has the most IAM-native approach of the three hyperscalers. Model access is governed by:

- **IAM policies**: `bedrock:InvokeModel` with `Resource: arn:aws:bedrock:region::foundation-model/model-id`
- **Model access requests**: For some models (Llama, Command, Jamba), you must explicitly request access via the Bedrock console. This is a one-time form submission.
- **No API keys for Bedrock-native models**: You authenticate with AWS SigV4 signing — no API key management for the built-in catalog.

For external providers, Bedrock offers **"Custom models"** and **"Imported models"** — you upload a model or configure a custom endpoint. These use IAM roles + S3 for model artifacts.

### Credential management model

- **Built-in models**: IAM role → no API key management
- **Model access**: Request-and-approve workflow via console (1-5 business days for some models)
- **External endpoints**: IAM roles + Bedrock API for custom model configuration
- **Multi-account**: AWS Organizations allows centralized model access policies across accounts

### What's notable

Bedrock's IAM-centric model is the most auditable and most enterprise-compliant for AWS shops. The elimination of API keys for built-in models removes an entire class of credential management problems. However, this only works in AWS-native environments. For organizations that need to call OpenAI directly (non-Bedrock), they're back to managing API keys themselves.

The **request-and-approve** model for certain models (Llama 3) is worth noting: it forces a deliberate decision to enable a model, creating an audit trail and a review checkpoint. This is analogous to mingai's Draft → Published lifecycle in `llm_library`, but applied at the infrastructure layer.

### Gap vs. mingai's requirement

Same multi-tenant gap as Vertex and AI Foundry. AWS Bedrock is designed for organizations, not for SaaS platforms serving organizations.

---

## 4. Dify (Open Source)

### How it works

Dify is an open-source LLM application platform that is the most direct functional analogue to mingai's platform-level provider management. It implements exactly the pattern mingai is building.

**Provider Configuration UI** (Settings → Model Provider):

- List of supported providers: OpenAI, Anthropic, Azure OpenAI, Cohere, HuggingFace, Ollama, etc.
- For each provider: a form to enter API key, endpoint (for Azure), and model list
- Credentials stored in the Dify database, encrypted at rest (AES-256)
- A "Test" button on each credential form — fires a small test completion to validate before saving

**Model Configuration**:

- After configuring a provider, you select which models from that provider to enable
- Each model can be set as the "default" for a given operation type (text generation, embedding, speech-to-text, reranking)
- The distinction between "provider credentials" and "model selection" is explicitly maintained

**Per-workspace (multi-tenant) override**:

- In Dify Cloud, each workspace can use the system-configured models (platform pays) or configure their own provider (BYOLLM equivalent)
- Workspace owners who configure their own API key are isolated from the platform's provider

### Credential management model

| Layer            | Dify implementation                          |
| ---------------- | -------------------------------------------- |
| Credential store | Database-backed, AES-256 encrypted           |
| Credential entry | Web UI form per provider                     |
| Validation       | "Test" button fires sample completion        |
| Default model    | Explicit "set as default" per operation type |
| Multi-tenant     | System models vs. workspace-own models       |
| Key masking      | API key shown as `sk-...****` after save     |

### What's notable

Dify is the clearest reference implementation for what mingai needs. Three observations:

1. **The two-layer model is explicit**: In Dify, you first configure a provider (credentials), then separately configure which models from that provider to use. This exactly matches the `llm_providers` + `llm_library` two-table design.

2. **Test-before-save is standard**: The "Test" button is not an enhancement — it is table stakes for any LLM credential management UI. Users will enter wrong credentials. The test button is the difference between "save and discover the error when the first user query fails" vs. "discover the error immediately in the UI."

3. **Default model per operation type**: Dify has explicit "default for text generation," "default for embedding," etc. — exactly the slot model (intent, chat, vision, embedding) that mingai's architecture specifies.

### Gap vs. mingai's requirement

Dify's credential encryption key is stored alongside the database (same .env pattern as current mingai). This creates the same key management problem at a different layer. Mingai's Fernet approach, derived from `JWT_SECRET_KEY` via PBKDF2, is actually more secure because the key is derived rather than stored directly.

---

## 5. OpenWebUI

### How it works

OpenWebUI is an open-source local LLM management interface, primarily designed for Ollama but extending to OpenAI-compatible APIs and direct API providers.

**Admin panel provider configuration**:

- Settings → Admin → Connections
- Separate sections for "OpenAI API connections" and "Ollama API connections"
- For OpenAI-compatible: URL + API key, named connection
- Multiple connections can be configured simultaneously (e.g., local Ollama + OpenAI + Anthropic via proxy)
- Each model from each connection appears in a unified model list

**Model management**:

- Models are "pulled" from connected providers into a unified catalog
- Users select models from the merged list regardless of provider
- Admin can restrict which models specific user groups can access

### Credential management model

| Aspect           | OpenWebUI                                                             |
| ---------------- | --------------------------------------------------------------------- |
| Credential store | Application database (SQLite or PostgreSQL)                           |
| Entry method     | Admin panel form                                                      |
| Multi-provider   | Supported — multiple OpenAI-compatible endpoints                      |
| Model discovery  | Automatic (fetches model list from API endpoint)                      |
| Key storage      | Stored as-is in DB (no dedicated encryption beyond DB-level security) |
| Access control   | Per-model RBAC for user groups                                        |

### What's notable

OpenWebUI demonstrates that **automatic model discovery** is feasible — when you add an OpenAI-compatible endpoint, it fetches `/v1/models` and imports the model list automatically. This removes the need for the admin to manually register each model. For mingai, this would mean: add an Azure OpenAI resource, click "Discover Models", and the system automatically creates `llm_library` draft entries for each deployment on that resource.

OpenWebUI also makes a pragmatic choice: don't encrypt credentials specially, rely on database-level security. This is acceptable for a self-hosted single-organization tool but insufficient for a multi-tenant SaaS where the database credential is more broadly distributed.

### Gap vs. mingai's requirement

OpenWebUI is a single-organization tool. Multi-tenant SaaS requirements (provider-per-tenant, RBAC on provider access, audit trails) are not in scope. The credential security model (plain storage) would fail a SOC 2 audit.

---

## 6. Flowise

### How it works

Flowise is an open-source LLM flow/agent builder with a no-code interface. Its credential management is node-based:

**Credential system**:

- Each LLM node (e.g., "ChatOpenAI," "AzureChatOpenAI") has a "Credentials" field
- Clicking the credential field opens a credential manager: list of saved credentials, "Add New"
- A credential is a named key-value store: e.g., `{name: "my-openai-key", openAIApiKey: "sk-..."}`
- Credentials are stored encrypted in the Flowise database (AES-256 with a key from `FLOWISE_SECRETKEY_OVERWRITE` or auto-generated)
- Credentials can be reused across multiple nodes and flows

**What makes it distinct**:

- Credentials are **typed** — the credential form is different for OpenAI vs. Azure OpenAI vs. Anthropic (correct fields per provider)
- Each credential record has a name that is referenced by flows, decoupling the secret value from the flow configuration
- Changing a credential (e.g., rotating an API key) automatically propagates to all flows using that credential

### Credential management model

| Aspect            | Flowise                                                      |
| ----------------- | ------------------------------------------------------------ |
| Credential store  | Database, AES-256 encrypted with FLOWISE_SECRETKEY_OVERWRITE |
| Entry method      | Typed form per provider type                                 |
| Reference by name | Yes — flows reference credential name, not value             |
| Propagation       | Key rotation propagates to all uses                          |
| Audit             | No dedicated audit trail in core open-source version         |

### What's notable

Flowise's **reference-by-name** pattern is worth adopting. Rather than embedding credential data in flow configurations, flows reference a credential by name. This means:

1. Credential rotation (new API key) updates one record; all flows pick up the new value automatically
2. The same credential can be shared across many use cases without duplicating the secret
3. Flows can be exported/shared without embedding sensitive values

For mingai, this suggests that `llm_providers` entries should be referenced by ID/name from `tenant_configs`, rather than caching decrypted credential values anywhere except in-memory at call time.

---

## 7. Key Insight: The Enterprise-Friendly Pattern

Having analyzed six platforms, the most enterprise-friendly credential management pattern has four invariants:

### Invariant 1: Explicit Two-Layer Model

The **model catalog** (what models exist, capabilities, pricing) must be strictly separated from the **connection/credential store** (how to call them). Conflating these creates either security problems (credentials in model metadata) or operational problems (can't rotate a key without touching model definitions).

**Evidence**: AI Foundry (Connections vs. Model Catalog), Dify (Provider credentials vs. Model selection), Flowise (Credentials vs. Flow nodes).

### Invariant 2: Test Before Commit

Every enterprise credential entry UI that is serious about production use includes a "Test Connection" or equivalent that fires a real API call before saving. This is not optional — it is the difference between a credential management UI and a credential persistence form that happens to look like a credential management UI.

**Evidence**: AI Foundry (Chat playground), Dify (Test button), Flowise (implicit via node execution).

### Invariant 3: Reference by Name / ID, Not Inline Value

Credential values must be stored exactly once and referenced by an opaque identifier everywhere else. The reference is what gets cached, serialized, and passed around. The decrypted value exists only in-memory at call time.

**Evidence**: GCP Secret Manager (secret resource names), Flowise (credential names in flows), AWS Bedrock (ARN-based resource references).

### Invariant 4: Audit Trail + Key Masking

Enterprise platforms log every credential creation and modification event. API keys shown in UI after save must be masked (last 4 chars only). The audit trail is often a compliance requirement (SOC 2, ISO 27001).

**Evidence**: Azure Monitor integration in AI Foundry, GCP Cloud Audit Logs for Secret Manager, Flowise audit logs in enterprise edition.

---

## 8. Competitive Matrix

| Feature                         |  Vertex AI  |   AI Foundry    |  Bedrock   |     Dify      | OpenWebUI |     Flowise     | mingai (target) |
| ------------------------------- | :---------: | :-------------: | :--------: | :-----------: | :-------: | :-------------: | :-------------: |
| UI credential entry             |     No      |       Yes       |  Partial   |      Yes      |    Yes    |       Yes       |       Yes       |
| Test-before-save                |     N/A     |       Yes       |    N/A     |      Yes      |    No     |    Implicit     |       Yes       |
| Multi-provider simultaneously   |     Yes     |       Yes       |    Yes     |      Yes      |    Yes    |       Yes       |       Yes       |
| Encryption at rest              |     IAM     |    Key Vault    |    IAM     |    AES-256    | DB-level  |     AES-256     |  Fernet/PBKDF2  |
| Audit trail                     | Cloud Audit |  Azure Monitor  | CloudTrail |    Limited    |    No     |       No        |     Planned     |
| Multi-tenant provider isolation |     No      |       No        |     No     |    Partial    |    No     |       No        | Yes (core req)  |
| Default provider concept        |     Yes     |       Yes       |    Yes     |      Yes      |    No     |       No        |       Yes       |
| Key masking in UI               |     N/A     |       Yes       |    N/A     |      Yes      |    No     |       No        |       Yes       |
| Reference-by-name pattern       |     IAM     | Connection name |    ARN     | Provider name |    No     | Credential name |   Provider ID   |
| Model discovery from endpoint   |     No      |       Yes       |     No     |      No       |    Yes    |       No        |  Future scope   |
| No-restart key rotation         |     N/A     |       Yes       |    N/A     |      Yes      |    Yes    |       Yes       |  Yes (target)   |

---

## 9. Recommendation for mingai

The pattern that best fits mingai's requirements is the **Dify model** (closest functional analogue) combined with **AI Foundry's Connection concept** (clearest enterprise implementation), adapted for mingai's multi-tenant SaaS context.

Specifically:

1. **`llm_providers` table** = AI Foundry "Connections" + Dify "Provider Credentials". Named entries with typed fields per provider type, encrypted at rest.

2. **Provider-scoped test endpoint** = Dify "Test" button. Fire a real completion before saving. Return latency + response so Platform Admin has confidence.

3. **Reference-by-provider-ID** everywhere. `tenant_configs` references `llm_providers.id`, not raw credentials. Cache the provider config (not decrypted values) in Redis.

4. **`is_default` flag** = Dify's "Default model" concept. One provider per operation type can be marked default; new tenants inherit it automatically.

5. **Key masking** in all API responses. Return `key_last4: "X8k2"` and `key_set: true`, never the encrypted token or plaintext.

The one thing none of the competitors do that mingai must do: **per-tenant provider override**. Platform configures default providers; Enterprise tenants can be routed to dedicated providers (or use BYOLLM). This is a differentiator that requires the multi-tenant layer none of the six platforms above offer.

---

**Document Version**: 1.0
**Author**: Analysis Agent
**References**: Dify GitHub (langgenius/dify), Flowise GitHub (FlowiseAI/Flowise), Azure AI Foundry documentation, Vertex AI Agent Builder documentation, AWS Bedrock documentation, OpenWebUI documentation
