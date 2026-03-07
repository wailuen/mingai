# 13-01 — Profile & Memory: Product Opportunity

**Feature**: User Profile Learning + Working Memory + Memory Notes + Org Context
**Research date**: 2026-03-06
**Stage**: Analysis → Plan

---

## 1. Problem Statement

### 1.1 The Core Pain (First Principles)

Enterprise AI assistants fail because they treat every session as a blank slate. The user's mental model is: "This AI should know me by now." The product reality is: "It doesn't."

This creates three compounding frictions:

1. **Re-explanation tax**: User must re-state their role, context, and preferences in every session. Estimated cost: 30–90 seconds of repeated context-setting per session.
2. **Generic response penalty**: Without user context, the AI gives mid-tier answers — not wrong enough to distrust, not specific enough to be genuinely useful. Reduces perceived value.
3. **Progressive disengagement**: Users who feel "the AI doesn't get me" reduce usage frequency. Churn risk increases after week 2 if no personalization signal.

### 1.2 Why Enterprise Is Worse Than Consumer

- Consumer ChatGPT/Claude users have lower expectations and lower stakes
- Enterprise users have professional identity context (role, dept, regional regulations) that radically changes what a "good answer" looks like
- Enterprise sessions are often task-resumption (returning to a multi-day investigation) — broken context is high-cost

### 1.3 What Users Actually Need

Not just "remember my preferences" — but **contextual intelligence**:

- Know WHO I am (org identity, role, region)
- Know WHAT I prefer (communication style, technical depth)
- Know WHAT I told you (explicit notes)
- Know WHAT I've been working on (session continuity)

---

## 2. Market Landscape

### 2.1 Competitive Matrix

| Product           | Org Identity         | Learned Profile                     | Explicit Memory                | Session Continuity   | Enterprise Privacy |
| ----------------- | -------------------- | ----------------------------------- | ------------------------------ | -------------------- | ------------------ |
| ChatGPT           | None                 | Weak (global memory, unpredictable) | Yes (but leaky)                | None                 | Poor               |
| Microsoft Copilot | M365 Graph (partial) | None                                | None                           | None                 | Strong             |
| Glean             | LDAP/SSO context     | None                                | None                           | None                 | Strong             |
| Guru              | None                 | None                                | None                           | None                 | Strong             |
| Notion AI         | None                 | None                                | None                           | None                 | Moderate           |
| **mingai**        | Azure AD + SSO       | LLM-extracted every 10 queries      | User-directed + auto-extracted | Redis working memory | Native enterprise  |

### 2.2 Market Gap

No enterprise AI assistant simultaneously delivers:

1. Org identity awareness from corporate directory
2. Automatically learned behavioral profile
3. User-controlled explicit memory notes
4. Session continuity via working memory

Microsoft Copilot comes closest (M365 Graph = org data), but has no learned profile or explicit memory. ChatGPT has memory but no org context and weak privacy controls for enterprise.

**Gap = Org Identity × Learned Profile × User Memory × Enterprise Privacy**

---

## 3. Value Propositions

**VP-1: Responses calibrated to who you are at work** — not just what you asked, but your role, region, function, and expertise level.

**VP-2: Zero-setup personalization** — profile builds automatically from usage, no manual configuration required.

**VP-3: The AI remembers what you told it** — explicit memory notes persist across sessions, eliminating re-explanation.

**VP-4: Cross-session continuity** — returning users feel recognized ("you asked about AWS bonus last time").

**VP-5: Full data control** — view, edit, delete, or export everything the AI knows about you. GDPR-native.

---

## 4. Unique Selling Points (Critical Scrutiny)

### USP-1: Layered Contextual Intelligence (Org + Profile + Memory + Continuity)

**Claim**: mingai is the only enterprise RAG platform that stacks four distinct personalization layers into every query — organizational identity, learned behavioral profile, user-directed memory notes, and session working memory — producing responses that feel genuinely calibrated to the individual.

**Scrutiny**:

- Salesforce Einstein does personalization, but in CRM context only
- Microsoft Copilot has org graph data, but no learned profile or memory
- No known competitor ships all four layers simultaneously
- **Verdict**: USP holds. But it is a capability USP, not an outcome USP. Must translate to outcome language: "The AI that gets you right — every time, from day one."

### USP-2: Role-Specific Response Framing Without Hardcoding

**Claim**: Org context is injected as raw identity data and LLM interprets it contextually — handling any job title, department, or country without static mapping tables. This means it works for every enterprise out-of-the-box.

**Scrutiny**:

- Competitor solutions that attempt role-aware AI use brittle keyword matching or rigid persona mapping
- This LLM-interpretation approach is genuinely novel in enterprise RAG
- Risk: LLM may misinterpret unusual titles (e.g., "Chief of Staff" → generalist vs. strategic role?)
- **Verdict**: USP holds if demonstrated with concrete examples. Must be validated with >5 job title categories.

### USP-3: Dual-Path Memory (Auto-Learn + User-Directed)

**Claim**: Users can say "remember that I prefer concise bullet points" for instant memory, while the system simultaneously auto-extracts facts from conversation patterns — requiring zero extra effort.

**Scrutiny**:

- ChatGPT has "remember" commands, but no auto-extraction from conversations
- The combination of both paths + enterprise privacy controls + audit trail is unique
- Risk: Auto-extracted notes may feel intrusive if low-quality (users see spurious facts)
- **Verdict**: Strong USP. Requires rigorous quality threshold for auto-extraction (precision > recall).

---

## 5. The 80/15/5 Mapping

### 80% — Reusable Core (Platform-Agnostic)

- ProfileLearningService: trigger mechanism, LRU cache, merge strategy, GDPR controls
- WorkingMemoryService: Redis storage, topic extraction, returning-user detection
- Memory notes: schema, CRUD API, intent detection, prompt injection
- System prompt layer architecture (Layers 2–4)
- Privacy settings UI components

### 15% — Tenant Self-Service Configuration

- Per-tenant memory policy: enable/disable profile learning for all users
- Memory note retention period (configurable beyond 15-note default)
- Org context fields: which fields to expose (some tenants may exclude manager info by policy)
- Agent-scoped memory policy: tenant admin can configure whether memories apply per-agent or globally

### 5% — True Customization

- Custom org identity source (non-Azure AD: Okta, Workday, custom LDAP)
- White-label privacy settings page
- Bespoke memory extraction prompts for specialized domains

---

## 6. Open Questions (For Plan)

1. **Agent-scoped memories**: Should memories be global (cross-agent) or per-agent? aihub2 is global. For multi-agent mingai, per-agent isolation is probably correct for enterprise.
2. **Multi-tenant memory isolation**: User in Tenant A should never leak to Tenant B. Already guaranteed by tenant_id-scoped Redis keys, but needs explicit architecture spec.
3. **Team-level shared memory**: No team memory in aihub2. Is this a gap or a feature (privacy protection)?
4. **Memory for external SSO users without Azure AD**: Org context degrades to None — acceptable, but should be documented.
5. **Token budget under pressure**: At high glossary + domain prompt loads, 100-token working memory may be the first to be truncated. Need priority ordering.
