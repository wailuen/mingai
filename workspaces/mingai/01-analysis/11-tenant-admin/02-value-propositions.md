# 11-02 — Tenant Admin: Value Propositions

**Date**: 2026-03-05

---

## 1. Stakeholder Map

| Role                              | What they do                                        | What they need                                                                                                             |
| --------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Tenant Admin** (primary)        | Deploys and governs the organization's AI workspace | Self-service setup without engineering help; visibility into whether AI is working; control over access and agent behavior |
| **End User** (beneficiary)        | Uses AI agents to do their job                      | Fast, accurate answers; agents that know organizational context; reliable access to the right knowledge                    |
| **IT Security** (stakeholder)     | Approves AI tool deployment                         | Audit trail, SSO integration, data isolation guarantees, no credential exposure                                            |
| **Department Head** (stakeholder) | Sponsors AI adoption in their function              | ROI visibility (are my team members using this?), quality confidence (is the AI giving correct advice?)                    |
| **Platform Admin** (partner)      | Operates the underlying platform                    | Tenant admin self-sufficiency reduces support burden                                                                       |

---

## 2. Value Propositions by Stakeholder

### 2.1 Tenant Admin

**"Deploy enterprise AI without writing a single line of code or filing a single IT ticket."**

Today, deploying a meaningful enterprise AI assistant for an organization requires:

- Engineering time to connect document sources to RAG pipelines (weeks)
- IT admin time to configure SSO and RBAC (days)
- Ongoing engineering support when documents change or agents underperform
- No native tooling to see whether the AI is actually helping users

| Problem                                                        | How mingai Solves It                                                                  | Value                                                               |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| "Connecting SharePoint takes an engineer and 2 weeks"          | Step-by-step permission wizard with exact Azure portal instructions                   | Any IT admin can complete this in < 1 hour                          |
| "We don't know if the AI is using our actual documents"        | Sync dashboard with per-source document counts, freshness, and failure details        | Immediate visibility without checking AI Search directly            |
| "The AI doesn't understand our company terminology"            | Glossary management — add terms, definitions, context tags — no AI expertise required | Organization-specific AI accuracy without prompt engineering        |
| "We don't know who can access what in the AI"                  | KB and agent-level access control with role + user-specific grants                    | Same access governance as SharePoint, applied to AI                 |
| "Building an agent requires a developer"                       | Agent studio with system prompt UI, KB attachment, guardrail configuration            | Knowledge manager can build and deploy an agent without engineering |
| "We don't know if the AI is helping users or frustrating them" | Per-agent satisfaction dashboard, issue queue, low-confidence response alerts         | Visibility into AI quality without waiting for user complaints      |

### 2.2 End User (Indirect)

**"The AI actually knows our company's terminology and policies — it's not a generic chatbot."**

When the tenant admin properly configures the workspace:

- AI answers use the organization's actual documents (SharePoint sync, Google Drive sync)
- AI understands company-specific terms (glossary)
- Correct agents are surfaced to each user based on their role (RBAC)
- AI quality improves over time as the tenant admin fixes issues surfaced by feedback

The end user receives a better experience because the tenant admin had tools to create it.

### 2.3 IT Security / Compliance

**"Zero data leaves the organization's control without explicit configuration."**

- SSO integration means no separate credentials to manage
- Group-to-role sync means offboarding is instant (remove from IdP group → access revoked within next login)
- Audit log captures every configuration change with actor and timestamp
- KB access control means sensitive content (HR, Legal, Finance) is isolated to authorized users only
- Credential storage: SharePoint secrets and Google Drive service account keys stored encrypted, never exposed in API responses

### 2.4 Department Head / AI Sponsor

**"I can see whether my team is using it and whether it's working."**

- Active user count per agent per day/week
- Satisfaction rate per agent (are responses useful?)
- Feature adoption: which KBs are being queried most
- Issue resolution: reported problems and their resolution status
- These metrics are available without requesting a report from IT or engineering

---

## 3. Business Value Propositions

### 3.1 Time-to-Value: From Decision to Deployed AI in Hours, Not Weeks

**Without mingai's tenant admin console**: Enterprise AI deployment requires IT to configure SSO, engineers to set up document indexing pipelines, security reviews of credential handling, agent builders to create AI behaviors. Typical enterprise RAG deployment: 6-12 weeks.

**With mingai's tenant admin console**:

- SSO: tenant admin completes SAML/OIDC config in < 2 hours following the in-app wizard
- SharePoint: permission provisioning wizard with exact step-by-step Azure portal instructions — < 1 hour
- Google Drive: service account + DWD setup guide embedded in the UI — < 1 hour for Workspace admins
- First agent deployed from library: < 30 minutes (fill variables, publish)
- Custom agent in Agent Studio: < 2 hours for first draft

**Time-to-value**: 1-2 days for a fully functional AI workspace vs 6-12 weeks without.

**Economic value**: At $150-300/hour for engineering time, a 6-week deployment (30 engineer-days) costs $36,000-$72,000. Self-service setup reduces this to near-zero. For enterprise customers, this is the most visible ROI argument in the buying decision.

### 3.2 Operational Independence: IT Admin Without AI Expertise

Today's enterprise AI deployment creates an ongoing support dependency on engineering or the AI vendor. Every time:

- A SharePoint site adds new documents → someone needs to re-trigger sync
- A new employee joins → someone needs to add them to the right access groups
- An agent underperforms → someone needs to debug prompt and retrieval

With the tenant admin console, these become self-service operations for any IT admin. The organization does not need an AI specialist on staff.

**Staffing economics**: Enterprise AI adoption is limited by the supply of AI-capable IT administrators. A platform that enables a non-specialist IT admin to operate an AI workspace expands the addressable market by 10-30×.

### 3.3 Governance and Compliance Without Engineering

Enterprise IT security requirements for AI tools include: data isolation, SSO, audit logs, access control, no credential sharing. Without a proper admin interface, these requirements require custom engineering. With the tenant admin console:

- Data isolation: enforced by platform architecture (tenant-scoped indexes)
- SSO: configured via SAML/OIDC wizard (no custom code)
- Audit log: all admin actions captured, searchable
- Access control: KB and agent-level RBAC with role and user assignments
- Credential handling: secrets vault, rotation reminders

This makes the governance story sellable to enterprise security teams who would otherwise reject a platform without these controls.

### 3.4 AI Quality Ownership

The tenant admin is closest to the organization's content and users. They know when a SharePoint library contains outdated policies. They know which user complaints are valid. With feedback monitoring and issue resolution tools, the tenant admin becomes the **quality steward** for the organization's AI deployment — without needing to understand the underlying ML.

**Value**: Organizations with active tenant admins see faster improvement in AI response quality because configuration problems (missing glossary terms, incomplete document sync, misconfigured agents) are caught and fixed quickly.

---

## 4. The 80/15/5 Analysis

**80% agnostic (reusable across any organization deploying enterprise AI)**:

- Workspace setup wizard (branding, timezone, locale)
- SSO configuration (SAML 2.0, OIDC, JIT provisioning)
- SharePoint connection (Entra app registration, Graph API)
- Google Drive connection (Service Account + DWD, OAuth)
- Sync health monitoring (per-source status, document counts, failures)
- Glossary CRUD (add, edit, delete, import/export)
- User management (invite, role assignment, suspend, delete)
- KB-level access control (role-based and user-specific)
- Agent-level access control
- Feedback monitoring dashboard (satisfaction, issue queue)

**15% self-service configurable**:

- Which document sources to connect (org-specific: SharePoint site URLs, Drive folder IDs)
- Glossary content (entirely organization-specific)
- Agent names and configurations (organization-specific variable values in templates)
- Custom agents in Agent Studio (organization-specific system prompts, KB selections)
- User access assignments (organization-specific role assignments)

**5% customization**:

- Custom branding (white-label tenants)
- Domain-specific agent validation workflows (e.g., legal review before HR agent publishes)
- Bespoke access control logic (dynamic access rules based on org attributes)

This 80/15/5 split is genuine and strong. Enterprise knowledge management follows the same structural patterns across organizations — what differs is content and configuration, not the management mechanics.

---

## 5. Competitive Displacement Analysis

### Head-to-Head: vs. Microsoft Copilot M365

**Copilot wins when**: Organization is 100% Microsoft, existing M365 E5 licensing, IT team is Microsoft-specialized, no custom agent needs beyond standard Copilot.

**mingai wins when**: Organization uses Google Drive (non-M365) or mixed document stores; organization wants custom agent behaviors (Copilot is fixed); organization needs multi-model flexibility (Copilot is GPT-4 only); organization is not Microsoft-only and wants flexibility.

**Displacement strategy**: Start with organizations that have Google Workspace or mixed document stores. These are the organizations Copilot serves poorly.

### Head-to-Head: vs. Glean

**Glean wins when**: Organization prioritizes search over chat; needs the most connectors (100+); engineering team manages the deployment.

**mingai wins when**: Organization wants AI agents (not just search), needs glossary for organization-specific AI understanding, wants non-technical admin self-service, needs per-agent RBAC (Glean has no agent model).

**Displacement strategy**: Position as the "agent-native" alternative. Glean is for finding information; mingai is for AI that acts on that information.

### Head-to-Head: vs. Copilot Studio

**Copilot Studio wins when**: Organization is Azure-native, has Power Platform investment, needs Teams integration.

**mingai wins when**: Organization wants non-Microsoft document sources, wants simpler admin UX for non-Power-Platform users, needs cloud-agnostic deployment.
