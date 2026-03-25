# LLM Models & AI Services Reference

Covers all models to configure in the **LLM Library** (platform admin → LLM Profiles). Credentials map to `platform.llm_providers` + `platform.llm_models`. Run migration 0058 after setting env vars.

Sources: `aihub2` env files + `mingai/model.md` (Bedrock / Ollama).

---

## LLM Library Setup — Chat Models

| Display Name           | Provider     | Deployment / Model ID  | Region         | Status                      |
| ---------------------- | ------------ | ---------------------- | -------------- | --------------------------- |
| GPT-5.2 (Azure AI Hub) | Azure OpenAI | `aihub2-main`          | Southeast Asia | Active (default)            |
| Claude Sonnet 4.6      | AWS Bedrock  | `arn:.../8fo75fa52tmk` | ap-southeast-1 | Inactive — activate via UI  |
| Claude Haiku           | AWS Bedrock  | `arn:.../6wbz52t5c3rz` | ap-southeast-1 | Inactive — activate via UI  |
| Qwen 3.5 27B           | Ollama       | `qwen3.5:27b`          | Local          | Inactive — pull model first |

---

## 1. Primary Chat (Main RAG Responses)

| Field                | Value                                                                        |
| -------------------- | ---------------------------------------------------------------------------- |
| **Model**            | `gpt-5.2-chat`                                                               |
| **Deployment**       | `aihub2-main`                                                                |
| **Env var**          | `AZURE_OPENAI_PRIMARY_DEPLOYMENT=aihub2-main`                                |
| **Endpoint**         | `https://ai-cloudappintegrum8776ai770723526188.cognitiveservices.azure.com/` |
| **Env var**          | `AZURE_OPENAI_ENDPOINT`                                                      |
| **Key**              | `<see .env: AZURE_OPENAI_KEY>`                                               |
| **Env var**          | `AZURE_OPENAI_KEY`                                                           |
| **API version**      | `2024-12-01-preview`                                                         |
| **Env var**          | `AZURE_OPENAI_API_VERSION`                                                   |
| **Region**           | East US 2                                                                    |
| **Max tokens**       | `8192`                                                                       |
| **Temperature**      | `1`                                                                          |
| **Reasoning effort** | `none`                                                                       |

---

## 2. Intent Detection (Fast Classification)

| Field                | Value                                                |
| -------------------- | ---------------------------------------------------- |
| **Model**            | `gpt-5-mini`                                         |
| **Deployment**       | `intent5`                                            |
| **Env var**          | `AZURE_OPENAI_INTENT_DEPLOYMENT=intent5`             |
| **Endpoint**         | `https://aihub2-openai.cognitiveservices.azure.com/` |
| **Env var**          | `AZURE_OPENAI_INTENT_ENDPOINT`                       |
| **Key**              | `<see .env: AZURE_OPENAI_INTENT_API_KEY>`            |
| **Env var**          | `AZURE_OPENAI_INTENT_API_KEY`                        |
| **Region**           | Southeast Asia                                       |
| **Reasoning effort** | `none`                                               |

---

## 3. Document Embedding (Uploaded Files / Conversation Docs)

| Field          | Value                                                                             |
| -------------- | --------------------------------------------------------------------------------- |
| **Model**      | `text-embedding-3-large`                                                          |
| **Dimensions** | 3072                                                                              |
| **Deployment** | `text-embedding-3-large`                                                          |
| **Env var**    | `AZURE_OPENAI_DOC_EMBEDDING_DEPLOYMENT`                                           |
| **Endpoint**   | `https://aihub2-openai.cognitiveservices.azure.com/`                              |
| **Env var**    | `AZURE_OPENAI_DOC_EMBEDDING_ENDPOINT`                                             |
| **Key**        | `<see .env: AZURE_OPENAI_DOC_EMBEDDING_KEY>`                                      |
| **Env var**    | `AZURE_OPENAI_DOC_EMBEDDING_KEY` (or same as intent key)                          |
| **Region**     | Southeast Asia                                                                    |
| **Used for**   | Document upload index (`aihub-conversation-documents`), new SharePoint reindexing |

---

## 4. KB Embedding (Legacy Enterprise Search Indexes)

| Field          | Value                                                    |
| -------------- | -------------------------------------------------------- |
| **Model**      | `text-embedding-ada-002`                                 |
| **Dimensions** | 1536                                                     |
| **Deployment** | `text-embedding-ada-002`                                 |
| **Env var**    | `AZURE_OPENAI_KB_EMBEDDING_DEPLOYMENT`                   |
| **Endpoint**   | `https://aihub2-openai-eastus.openai.azure.com/`         |
| **Env var**    | `AZURE_OPENAI_KB_ENDPOINT`                               |
| **Key**        | `<see .env: AZURE_OPENAI_KB_KEY>`                        |
| **Env var**    | `AZURE_OPENAI_KB_KEY`                                    |
| **Region**     | East US                                                  |
| **Used for**   | Legacy KB indexes in `cogsearchopenai` (backward compat) |

---

## 5. Vision Model

| Field          | Value                                                               |
| -------------- | ------------------------------------------------------------------- |
| **Deployment** | `gpt-vision`                                                        |
| **Env var**    | `AZURE_OPENAI_VISION_DEPLOYMENT=gpt-vision`                         |
| **Endpoint**   | `https://cloud-m93ow3xu-australiaeast.cognitiveservices.azure.com/` |
| **Env var**    | `AZURE_OPENAI_VISION_ENDPOINT`                                      |
| **Key**        | `<see .env: AZURE_OPENAI_VISION_KEY>`                               |
| **Env var**    | `AZURE_OPENAI_VISION_KEY`                                           |
| **Region**     | Australia East                                                      |

---

## 6. Azure Speech Services (Batch Transcription)

| Field       | Value                          |
| ----------- | ------------------------------ |
| **Service** | Azure Speech Services          |
| **Key**     | `<see .env: AZURE_SPEECH_KEY>` |
| **Env var** | `AZURE_SPEECH_KEY`             |
| **Region**  | `southeastasia`                |
| **Env var** | `AZURE_SPEECH_REGION`          |

---

## 7. MCP Server LLM Configs (Australia East shared endpoint)

All MCP servers share the same Azure OpenAI endpoint in Australia East with separate deployments:

**Shared endpoint:** `https://cloud-m93ow3xu-australiaeast.cognitiveservices.azure.com/`
**Shared key:** `<see .env: AZURE_OPENAI_VISION_KEY>`

| MCP Server    | Deployment Name     | Env Var                                                         |
| ------------- | ------------------- | --------------------------------------------------------------- |
| PitchBook     | `mcp-pitchbook`     | `PITCHBOOK_AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_DEPLOYMENT` |
| Capital IQ    | `mcp-capiq`         | `CAPIQ_AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_DEPLOYMENT`     |
| iLevel        | `mcp-ilevel`        | `AZURE_OPENAI_DEPLOYMENT`                                       |
| Teamworks     | `mcp-teamwork`      | `AZURE_OPENAI_DEPLOYMENT`                                       |
| Bloomberg     | `mcp-bloomberg`     | `AZURE_OPENAI_DEPLOYMENT`                                       |
| Azure AD      | `mcp-azuread`       | `AZUREAD_AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_DEPLOYMENT`   |
| Oracle Fusion | `mcp-oracle-fusion` | `AZURE_OPENAI_DEPLOYMENT`                                       |
| AlphaGeo      | `mcp-alphageo`      | `AZURE_OPENAI_DEPLOYMENT`                                       |

**Perplexity MCP** uses a different Azure OpenAI endpoint (Southeast Asia):

- Endpoint: `https://aihub2-openai.cognitiveservices.azure.com`
- Key: `<see .env: AZURE_OPENAI_INTENT_API_KEY>`
- Deployment: `mcp-perplexity`
- API version: `2025-04-01-preview`

---

## 8. Perplexity (Internet Search / Research)

| Field               | Value                                                                              |
| ------------------- | ---------------------------------------------------------------------------------- |
| **API Key**         | `<see .env: PERPLEXITY_API_KEY>`                                                   |
| **Env var**         | `PERPLEXITY_API_KEY`                                                               |
| **Fast model**      | `sonar`                                                                            |
| **Research model**  | `sonar-pro`                                                                        |
| **Reasoning model** | `sonar-reasoning`                                                                  |
| **Env vars**        | `PERPLEXITY_MODEL_FAST`, `PERPLEXITY_MODEL_RESEARCH`, `PERPLEXITY_MODEL_REASONING` |

---

## 9. Azure AI Search (Vector Search)

### Primary (Southeast Asia)

| Field         | Value                                         |
| ------------- | --------------------------------------------- |
| **Endpoint**  | `https://aihub2-ai-search.search.windows.net` |
| **Admin key** | `<see .env: AZURE_SEARCH_ADMIN_KEY>`          |
| **Query key** | `<see .env: AZURE_SEARCH_QUERY_KEY>`          |
| **Index**     | `aihub-conversation-documents`                |
| **Embedding** | `text-embedding-3-large` (3072 dims)          |

### Legacy (East US)

| Field         | Value                                        |
| ------------- | -------------------------------------------- |
| **Endpoint**  | `https://cogsearchopenai.search.windows.net` |
| **Admin key** | `<see .env: AZURE_SEARCH_LEGACY_ADMIN_KEY>`  |
| **Embedding** | `text-embedding-ada-002` (1536 dims)         |

---

## 10. Azure Document Intelligence

| Field        | Value                                                |
| ------------ | ---------------------------------------------------- |
| **Endpoint** | `https://southeastasia.api.cognitive.microsoft.com/` |
| **Key**      | `<see .env: AZURE_DOCUMENT_INTELLIGENCE_KEY>`        |
| **Env var**  | `AZURE_DOCUMENT_INTELLIGENCE_KEY`                    |
| **Used for** | PDF, DOCX, XLSX, PPTX extraction                     |

---

## 11. AWS Bedrock — ap-southeast-1

| Field            | Value                                  |
| ---------------- | -------------------------------------- |
| **Region**       | `ap-southeast-1`                       |
| **Account**      | `106056766526`                         |
| **Bearer token** | `<see .env: AWS_BEDROCK_BEARER_TOKEN>` |
| **Env var**      | `AWS_BEDROCK_BEARER_TOKEN`             |

**Application Inference Profiles:**

| Display Name      | Profile ID     | Full ARN                                                                                 |
| ----------------- | -------------- | ---------------------------------------------------------------------------------------- |
| Claude Sonnet 4.6 | `8fo75fa52tmk` | `arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/8fo75fa52tmk` |
| Claude Haiku      | `6wbz52t5c3rz` | `arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/6wbz52t5c3rz` |

**LLM Library setup:** Add provider `AWS Bedrock`, region `ap-southeast-1`. Both models start inactive — activate via platform admin UI after adding credentials.

---

## 12. Ollama — Local

| Field        | Value                    |
| ------------ | ------------------------ |
| **Endpoint** | `http://localhost:11434` |
| **Model**    | `qwen3.5:27b`            |

**LLM Library setup:** Add provider `Ollama`, endpoint `http://localhost:11434`, model `qwen3.5:27b`, display name `Qwen 3.5 27B (Ollama)`, region `Local`.
Pull model first: `ollama pull qwen3.5:27b`

---

## Summary Table

| Model                    | Purpose                | Provider                      | Deployment / ARN / ID    | LLM Library    |
| ------------------------ | ---------------------- | ----------------------------- | ------------------------ | -------------- |
| `gpt-5.2-chat`           | Main RAG chat          | Azure OpenAI (East US 2)      | `aihub2-main`            | ✅ Active      |
| `gpt-5-mini`             | Intent detection       | Azure OpenAI (SEA)            | `intent5`                | Internal only  |
| `text-embedding-3-large` | Doc embeddings         | Azure OpenAI (SEA)            | `text-embedding-3-large` | Not applicable |
| `text-embedding-ada-002` | KB embeddings (legacy) | Azure OpenAI (East US)        | `text-embedding-ada-002` | Not applicable |
| `gpt-vision`             | Vision/image analysis  | Azure OpenAI (Australia East) | `gpt-vision`             | Internal only  |
| MCP models (8x)          | MCP tool-use reasoning | Azure OpenAI (Australia East) | `mcp-*` deployments      | Not applicable |
| `sonar`                  | Fast internet search   | Perplexity                    | —                        | Not applicable |
| `sonar-pro`              | Deep research          | Perplexity                    | —                        | Not applicable |
| `sonar-reasoning`        | Reasoning search       | Perplexity                    | —                        | Not applicable |
| Claude Sonnet 4.6        | General chat           | AWS Bedrock (ap-southeast-1)  | `arn:.../8fo75fa52tmk`   | ⏸ Inactive     |
| Claude Haiku             | Fast/cheap chat        | AWS Bedrock (ap-southeast-1)  | `arn:.../6wbz52t5c3rz`   | ⏸ Inactive     |
| `qwen3.5:27b`            | Local chat             | Ollama (localhost)            | `qwen3.5:27b`            | ⏸ Inactive     |
| Azure Speech             | Batch transcription    | Azure Cognitive               | —                        | Not applicable |
| Azure Doc Intelligence   | Document extraction    | Azure Cognitive               | —                        | Not applicable |
