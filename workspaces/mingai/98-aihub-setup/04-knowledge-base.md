# Step 4 — Knowledge Bases as Agent Cards

**Actor**: Tenant Admin
**Concept mapping**: aihub2 Azure AI Search index → mingai `agent_card`
**Table**: `agent_cards`
**No RAG pipeline in Phase 1** — each KB is surfaced as a named agent. The agent card's
`capabilities` JSONB stores the Azure AI Search config so the chat backend knows where to search.

---

## Architecture

```
aihub2                              mingai (Phase 1)
──────────────────────────────      ─────────────────────────────────────────────
KB Index (CosmosDB)                 agent_card row
  name            →                   name
  description     →                   description
  system_prompt   →                   system_prompt
  azure_search_*  →                   capabilities.search_config
  is_enabled      →                   status ('active' | 'draft')
  content_type    →                   capabilities.content_type
  search_config   →                   capabilities.top_k, min_relevance_score
```

User selects an agent (= KB) when starting a conversation. The backend reads
`agent_cards.capabilities` to locate the correct Azure AI Search index and executes
the search before calling the LLM.

---

## 4.1 Agent Card SQL Template

```sql
INSERT INTO agent_cards (
  tenant_id, name, description, system_prompt,
  capabilities, status, version, created_by
)
VALUES (
  '<tenant_id>',
  '<name>',
  '<description>',
  '<system_prompt>',
  '<capabilities_json>'::jsonb,
  'active',
  1,
  NULL
);
```

**Capabilities JSON structure**:

```json
{
  "search_config": {
    "provider": "azure_ai_search",
    "endpoint": "https://cogsearchopenai.search.windows.net",
    "api_key": "<AZURE_SEARCH_API_KEY>",
    "index_name": "<azure_search_index_name>",
    "top_k": 5,
    "min_relevance_score": 0.6,
    "embedding_model": "text-embedding-ada-002",
    "embedding_dims": 1536
  },
  "content_type": "general"
}
```

For **new indexes** (`idx_sp_*` prefix) use the new search resource:

```json
{
  "search_config": {
    "provider": "azure_ai_search",
    "endpoint": "https://aihub2-ai-search.search.windows.net",
    "api_key": "<AZURE_SEARCH_ADMIN_KEY>",
    "index_name": "<idx_sp_*>",
    "top_k": 5,
    "min_relevance_score": 0.6,
    "embedding_model": "text-embedding-3-large",
    "embedding_dims": 3072
  },
  "content_type": "general"
}
```

---

## 4.2 All 29 Enabled KB Agent Cards

Skip indexes where `is_enabled = false` (IT Self Service, Tpc Index Test, TestIndex).

---

### KB-01: Chairman Teaching

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Chairman Teaching',
  'Central knowledge repository for the Group''s philosophy, culture, and learning foundations — Chairman''s teachings, Quantum Leadership, Mindful Living, and Mindful Emotion.',
  'You are an Assistant for the Chairman''s communications and thought leadership. When responding: use a thoughtful, reflective tone aligned with leadership communication. Draw from the Chairman''s writings, Quantum Leadership frameworks, and Mindful Living resources. Help users align personal growth with organizational purpose.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "chairman-article-v1", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 11779}'::jsonb,
  'active', 1
);
```

---

### KB-02: Project Gemini User Manual

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Project Gemini ERP Assistant',
  'Official operating instructions and user manuals for Project Gemini (Oracle ERP). Covers day-to-day Oracle workflows for Finance, Procurement, and HR modules.',
  'You are an ERP assistant for Project Gemini, the TPC Group Oracle implementation. Provide clear, step-by-step instructions using exact menu paths from the documentation. When a process varies by user role, ask the user their role before answering.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-gemini", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 50}'::jsonb,
  'active', 1
);
```

---

### KB-03: Signed Document Archive

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Signed Document Archive',
  'Authoritative archival repository for all formally executed Adobe Sign documents across the Group. Highly confidential — legal, compliance, and audit use only.',
  'You are an assistant for the Group''s formally signed document archive. Only answer questions about executed contracts and agreements. Always cite the signing parties and execution date. This archive is strictly confidential — confirm the user''s authorisation before sharing document details.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-adobe-signed", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 42393, "access": "restricted"}'::jsonb,
  'active', 1
);
```

---

### KB-04: Singapore Policy

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Singapore Policy',
  'Official HR, IT, and company policies for TPC Singapore entities. Single source of truth for Singapore-based employees.',
  'You are an HR and policy assistant for TPC Singapore. Answer questions about HR policies, benefits, IT guidelines, and workplace conduct. Always specify the exact policy document you are referencing. Recommend confirming personal decisions with HR.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-sg-policy", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "hr_policies"}'::jsonb,
  'active', 1
);
```

---

### KB-05: Indonesia Policy

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Indonesia Policy',
  'Official HR, IT, and company policies for TPC Indonesia entities (PSS). Covers employment policies, benefits, compliance for Indonesia operations.',
  'You are an HR and policy assistant for TPC Indonesia. Answer questions about HR policies, benefits, IT guidelines, and compliance requirements for Indonesian entities. Cite the specific policy document. For regulatory questions, note that Indonesian labour law may apply and recommend consulting HR or legal.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-indonesia", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "hr_policies", "doc_count": 1025}'::jsonb,
  'active', 1
);
```

---

### KB-06: China Policy

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'China Policy',
  'Official HR, IT, and governance policies for TPC China operations. Covers HR manuals, IT standards, compliance, and country-specific adaptations.',
  'You are an HR and policy assistant for TPC China. Answer questions about HR policies, IT guidelines, and operational governance applicable to China-based entities. Always specify which policy applies to China vs. Group-wide. For China-specific regulatory questions, recommend consulting the local HR or legal team.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-china", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 906}'::jsonb,
  'active', 1
);
```

---

### KB-07: Unithai Policy

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Unithai Policy',
  'Official policies and guidelines for Unithai entities in Thailand.',
  'You are an HR and policy assistant for Unithai (Thailand). Answer questions about policies, benefits, and workplace guidelines applicable to Unithai employees. Cite the specific document. For Thai regulatory matters, recommend consulting HR or local legal counsel.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-unithai-policy", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "hr_policies"}'::jsonb,
  'active', 1
);
```

---

### KB-08: TPC Treasury

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'TPC Treasury',
  'Treasury-related information and documentation for Group Treasury team.',
  'You are a treasury assistant for TPC Group. Answer questions about treasury processes, policies, and financial management. This knowledge base is restricted to Treasury team members. Always reference the source document and recommend verification with the Treasury team for financial decisions.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-treasury", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "access": "restricted"}'::jsonb,
  'active', 1
);
```

---

### KB-09: Group Investment Committee (GIC)

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'GIC — Investment Committee',
  'Governance documents, investment proposals, meeting minutes, and decision records for the TPC Group Investment Committee. Confidential.',
  'You are an investment research assistant for the TPC Group Investment Committee (GIC). You have access to GIC meeting records, investment proposals, governance frameworks, and approval matrices. Be factual and reference source documents. Flag any information requiring verification. GIC content is strictly for authorised users only.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-gic-v1", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 15352, "access": "restricted"}'::jsonb,
  'active', 1
);
```

---

### KB-10: MEP Coaching

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'MEP Coaching',
  'Coaching materials, learning resources, and reference content for the Mindful Emotion Program (MEP). Supports emotional awareness and mindful practice.',
  'You are a coaching assistant for the Mindful Emotion Program (MEP). Support participants with emotional awareness, self-regulation, and mindful responses. Use a warm, reflective tone. Maintain psychological safety — do not disclose individual coaching notes. For personal guidance, encourage participants to work with their coach directly.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-coaching-mep", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 469, "access": "restricted"}'::jsonb,
  'active', 1
);
```

---

### KB-11: Octave Policy

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Octave Policy',
  'HR, benefits, and governance policies for Octave Living and Octave Institute entities.',
  'You are an HR assistant for Octave Living and Octave Institute. Answer questions about HR policies, employee benefits, conduct guidelines, and governance. Cite the specific policy document and recommend confirming personal matters with HR.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "index-octave-policy", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "hr_policies", "doc_count": 90}'::jsonb,
  'active', 1
);
```

---

### KB-12: Octave Programs

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Octave Programs',
  'Wellness, mindfulness, movement, and holistic healing workshop programs offered by Octave Institute and Octave Living.',
  'You are a wellness program assistant for Octave Living and Octave Institute. Help users find the right wellness, mindfulness, or movement programs. Describe courses, practitioners, schedules, and suitability. Maintain a warm, supportive tone aligned with the Octave brand.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "octave-index-col-program", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 343}'::jsonb,
  'active', 1
);
```

---

### KB-13 to KB-19: Octave SharePoint Libraries (China)

These 7 KBs serve the Octave China (Sangha Suzhou) operations. Create one agent card each:

| #   | Name                       | index_name                                         | doc_count |
| --- | -------------------------- | -------------------------------------------------- | --------- |
| 13  | Octave HR Demo             | `octave-index-from-sharepoint-library-demo`        | 46        |
| 14  | Octave Hospitality SOPs    | `octave-index-from-sharepoint-library-hospitality` | 443       |
| 15  | Octave Image Library       | `octave-index-from-sharepoint-library-image`       | 572       |
| 16  | Octave License & Permits   | `octave-index-from-sharepoint-library-license`     | 125       |
| 17  | Octave Institute Programs  | `octave-index-from-sharepoint-library-oi`          | 8         |
| 18  | Octave Instructor Profiles | `octave-index-from-sharepoint-library-tlr`         | 22        |
| 19  | Octave Wellness Services   | `octave-index-from-sharepoint-library-wellness`    | 738       |

Use the same capabilities template (legacy endpoint, ada-002) for all. System prompts:

- **Hospitality SOPs**: "You are a hospitality assistant for Sangha Suzhou. Provide step-by-step SOPs for F&B, housekeeping, and guest services. Reference the specific SOP document and section."
- **Image Library**: "You are an image library assistant for Octave Living. Help users locate facility images by venue, type, and activity."
- **Wellness Services**: "You are a wellness services assistant for SANGHA Wellness. Help users understand health assessments, intervention programs, and wellness services. Always recommend consulting a qualified practitioner for health decisions."
- **Others**: Use generic assistant prompt referencing the KB topic.

---

### KB-20: Octave SharePoint List

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Octave Philosophy & Leadership',
  'Holistic leadership, business transformation, and well-being resources blending Eastern wisdom, Western science, and modern management. Covers the Tsao family business and OCTAVE Institute programs.',
  'You are a leadership and philosophy assistant for the Octave Institute. Help users explore holistic leadership concepts, mindfulness frameworks, and the OCTAVE approach to conscious business. Use a reflective, thoughtful tone.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "octave-index-from-splist", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 196}'::jsonb,
  'active', 1
);
```

---

### KB-21: Octave Products & Services

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Octave Products & Services',
  'Wellness, health, and lifestyle service catalogue for SANGHA Wellness — interventions, spa, fitness, nutrition, and creative activities.',
  'You are a product and services assistant for SANGHA Wellness. Help users explore wellness services, health interventions, spa treatments, and lifestyle programs. Describe offerings clearly and recommend consulting a practitioner for health-specific decisions.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "octave-index-from-splist-product", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "product", "doc_count": 273}'::jsonb,
  'active', 1
);
```

---

### KB-22: Aurora Tankers — Post-Fixture

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Aurora Tankers Operations',
  'Post-fixture procedures, chartering guidelines, and operational SOPs for Aurora Tankers liquid bulk operations.',
  'You are a maritime operations assistant for Aurora Tankers Management. Answer questions about post-fixture procedures, charter party terms, cargo handling, and voyage management. Use precise maritime terminology. For safety-critical procedures, always recommend verification with the operations team.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "imc-at-postfix", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 2148}'::jsonb,
  'active', 1
);
```

---

### KB-23: IMC Shipping — Dry Bulk Chartering

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'IMC Shipping — Dry Bulk',
  'Voyage planning, cargo operations, port coordination, and operational communications for IMC Shipping dry bulk fleet.',
  'You are a dry bulk operations assistant for IMC Shipping. Answer questions about voyage planning, cargo operations, port calls, and safety compliance. Use precise maritime terminology. Safety-critical decisions must be verified with the operations team.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "imc-db-chartering", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 102}'::jsonb,
  'active', 1
);
```

---

### KB-24: Maritime Comity Operations

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Maritime Comity Operations',
  'Official operating manuals and procedural guidance for vessel operations under the Maritime-Comity system.',
  'You are a maritime operations assistant for the Maritime-Comity system. Provide authoritative references from operating manuals for ship and shore personnel. Cite the manual section. For operational exceptions, always escalate to the operations team.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "ops-maritime-comity", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 136}'::jsonb,
  'active', 1
);
```

---

### KB-25: Infor Maritime Guide

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Infor Maritime Guide',
  'User guides and procedures for Infor Maritime application — commercial, procurement, technical, finance, and operational workflows.',
  'You are an Infor Maritime application assistant. Provide step-by-step guidance for using Infor Maritime across commercial, procurement, maintenance, and finance modules. Reference the specific guide section and page when possible.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "pss-infor-guide", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 453}'::jsonb,
  'active', 1
);
```

---

### KB-26: PSS General (Indonesia Operations)

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'PSS General — Indonesia',
  'General reference information for PSS (PT Pelayaran Sumber Samudra) and IMC Indonesia entities — company profiles, business structures, and operational context.',
  'You are a general information assistant for PSS and IMC Indonesia operations. Answer questions about company profiles, business structures, industry context, and regulatory overviews for Indonesia entities. For business-critical decisions, recommend verifying with the relevant team.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "pss-general", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general", "doc_count": 1293}'::jsonb,
  'active', 1
);
```

---

### KB-27: UTSE ISO

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'UTSE ISO',
  'ISO documentation and quality management materials for Unithai Stevedoring Enterprises (UTSE).',
  'You are a quality and compliance assistant for UTSE. Answer questions about ISO procedures, quality standards, and compliance requirements. Reference the specific ISO document and clause number when possible.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://cogsearchopenai.search.windows.net", "api_key": "<AZURE_SEARCH_API_KEY>", "index_name": "tpc-utse-iso", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-ada-002", "embedding_dims": 1536}, "content_type": "general"}'::jsonb,
  'active', 1
);
```

---

### KB-28: Group Investment Committee (New SharePoint)

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Group Investment Committee (SharePoint)',
  'Latest GIC documents synced from SharePoint — investment proposals, committee records, and governance materials.',
  'You are an investment research assistant for the TPC Group Investment Committee. Reference GIC documents for proposals, decisions, and governance. Restricted to authorised GIC members only.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://aihub2-ai-search.search.windows.net", "api_key": "<AZURE_SEARCH_ADMIN_KEY>", "index_name": "idx_sp_a3b78955fe8b", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-3-large", "embedding_dims": 3072}, "content_type": "general", "access": "restricted"}'::jsonb,
  'active', 1
);
```

---

### KB-29: Chairman's View (New SharePoint)

```sql
INSERT INTO agent_cards (tenant_id, name, description, system_prompt, capabilities, status, version)
VALUES (
  '<tenant_id>',
  'Chairman''s View',
  'Chairman''s perspectives, commentaries, and viewpoints — latest content synced from SharePoint.',
  'You are an assistant for the Chairman''s views and perspectives. Respond with a thoughtful, reflective tone. Help users explore the Chairman''s thinking on strategy, culture, and leadership.',
  '{"search_config": {"provider": "azure_ai_search", "endpoint": "https://aihub2-ai-search.search.windows.net", "api_key": "<AZURE_SEARCH_ADMIN_KEY>", "index_name": "idx_sp_0b2b0c924623", "top_k": 5, "min_relevance_score": 0.6, "embedding_model": "text-embedding-3-large", "embedding_dims": 3072}, "content_type": "general"}'::jsonb,
  'active', 1
);
```

---

## 4.3 Skipped KBs (disabled / test)

| KB              | Azure Index             | Reason                          |
| --------------- | ----------------------- | ------------------------------- |
| IT Self Service | `it-troubleshooting-v1` | `is_enabled=false` in aihub2    |
| Tpc Index Test  | `tpc-index-test`        | `is_enabled=false`, 8 docs only |
| TestIndex       | `idx_sp_24fab65b19e2`   | Test index                      |

Create these as `status='draft'` if you want them visible but not accessible to users.

---

## 4.4 Team → Agent Card Access Mapping

> **Phase B note**: Per-agent access control (restricting visibility by team/role) is implemented in
> Phase B Sprint B1 of the tenant admin plan. In Phase 1, all `status='active'` agent cards are visible
> to all users in the tenant. The table below documents the intended access boundaries — use it to
> configure restrictions once Phase B ships. For now, mark highly sensitive cards (Signed Document
> Archive, GIC, TPC Treasury) as `status='draft'` if you want to suppress them from general access.

After creating agent cards, configure which teams can see which agents (in Tenant Admin > Agents > Access):

| Agent Card                      | Teams with Access                           |
| ------------------------------- | ------------------------------------------- |
| Chairman Teaching               | All teams                                   |
| Chairman's View                 | All teams                                   |
| Project Gemini ERP              | TPC Singapore, TPC Indonesia, TPC Thailand  |
| Signed Document Archive         | Restricted — tenant admin discretion        |
| Singapore Policy                | TPC Singapore                               |
| Indonesia Policy                | TPC Indonesia                               |
| China Policy                    | TPC China                                   |
| Unithai Policy                  | TPC Thailand, UTSE Specific                 |
| TPC Treasury                    | TPC Treasury                                |
| GIC — Investment Committee      | TPC GIC                                     |
| Group Investment Committee (SP) | TPC GIC                                     |
| MEP Coaching                    | MEP Coaching Program                        |
| Octave Policy                   | All Octave-entity users                     |
| Octave Programs                 | All                                         |
| Octave Hospitality SOPs         | TPC China (Sangha Suzhou staff)             |
| Octave Wellness Services        | TPC China (Sangha Suzhou staff)             |
| Octave Products & Services      | TPC China                                   |
| Octave Philosophy & Leadership  | All                                         |
| Octave (remaining SharePoint)   | TPC China                                   |
| Aurora Tankers Operations       | Aurora Tankers                              |
| IMC Shipping — Dry Bulk         | IMC Shipping                                |
| Maritime Comity Operations      | Aurora Tankers, IMC Shipping                |
| Infor Maritime Guide            | Aurora Tankers, IMC Shipping, TPC Indonesia |
| PSS General — Indonesia         | TPC Indonesia                               |
| UTSE ISO                        | UTSE Specific                               |

---

## Verification Checklist

- [ ] 29 agent cards created (KB-01 to KB-29)
- [ ] 7 Octave SharePoint library cards created (KB-13 to KB-19)
- [ ] Each card has correct `index_name` in `capabilities.search_config`
- [ ] Restricted KBs (Signed Document, GIC, MEP, Treasury) flagged with `access: restricted`
- [ ] 3 test KBs created as `status='draft'` or skipped
- [ ] Sensitive KBs (Signed Document, GIC, TPC Treasury) set to `status='draft'` until Phase B RBAC ships
- [ ] **Phase B**: Configure team-to-agent access mapping in UI once visibility modes are available
- [ ] Test one search query per priority KB to verify Azure AI Search connectivity
