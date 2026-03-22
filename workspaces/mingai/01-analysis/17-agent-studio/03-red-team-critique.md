# 03 -- Agent Studio: Red Team Critique

> **Status**: Red Team Review
> **Date**: 2026-03-21
> **Reviewer**: deep-analyst (red team mode)
> **Documents Reviewed**: `01-gap-and-risk-analysis.md`, `02-ux-design-spec.md`, `33-agent-library-studio-architecture.md`, `23-agent-template-flows.md`
> **Verdict**: NEEDS REVISION

**One-sentence reason**: The analysis is technically thorough on backend gaps but fundamentally misses the end-user experience dimension of agents, underestimates the conceptual chasm between RAG-only and A2A agent types, and proposes a UX pattern (full-page overlay) that creates a precedent break without sufficient justification relative to a simpler progressive alternative.

---

## Finding 1: Agent Concept Clarity -- Template vs. Instance

**Severity**: MEDIUM (documentation gap, not a design flaw)

The gap analysis (doc 01, "What an Agent IS") provides the clearest articulation of the template/instance/runtime tiers seen anywhere in the mingai documentation. The three-tier model is well-defined: Tier 1 (platform-authored template), Tier 2 (tenant-configured instance), Tier 3 (runtime behavior). This is a genuine contribution.

**However, the boundary between what platform admins control and what tenant admins control is muddied in two places:**

1. **Guardrails ownership is ambiguous.** The gap analysis says "Tenants cannot override [guardrail rules]" for template-based agents, while the UX spec says custom agents have "tenant-editable" guardrails. This is correct for the two paths, but there is no discussion of what happens when a tenant admin ALSO wants to ADD guardrails on top of template guardrails. The architecture doc (33) does not address additive tenant guardrails. This creates a false binary: either the platform owns all guardrails (template agents) or the tenant owns all guardrails (custom agents). Enterprise buyers will want both -- platform baseline guardrails PLUS tenant-specific ones (e.g., a financial services tenant adding industry-specific compliance rules on top of a generic HR agent).

2. **The "Agent Studio" name is used for two different things.** In the UX spec, "Platform Admin -- Agent Template Studio" and "Tenant Admin -- Custom Agent Studio" share the "Studio" name but are fundamentally different operations. The platform admin creates a reusable template with variables, versioning, and plan gates. The tenant admin creates a one-off instance with no versioning. Calling both "Studio" implies equivalent capability and will confuse documentation, support tickets, and the UI itself. Recommendation: Reserve "Studio" for the platform admin surface. The tenant admin surface is "Custom Agent Builder" or simply "Create Custom Agent."

---

## Finding 2: Root Cause Diagnosis -- "Not What We Want"

**Severity**: HIGH (the analysis partially misses the deeper product problem)

The gap analysis concludes that the root cause is "the current UI treats [the system prompt] as the primary dimension, which is why the form feels inadequate." This is technically accurate but insufficient. The real diagnosis has three layers:

**Layer 1 (correctly identified):** The form is missing 4 of 7 configuration dimensions. This is a feature gap.

**Layer 2 (partially identified):** The form does not communicate what an agent IS. The analysis says "an agent is a governed pipeline, not a prompt" -- this is the right insight. But the analysis then jumps to "add 7 accordion sections" as the solution, which is adding fields to a form. The deeper problem is that the current form makes no visual distinction between a RAG-only agent (prompt + KB = done) and an A2A agent (prompt + KB + credentials + tools + guardrails). A platform admin creating the HR Policy Advisor (RAG-only, no credentials, no tools) should experience a much simpler authoring surface than one creating the Bloomberg Intelligence Agent (credentials, external API, tools, strict guardrails). The proposed 7-section accordion treats both identically.

**Layer 3 (not identified):** The product philosophy gap. The current form was built for RAG-only agents because that is what mingai has today. The 4 seed templates (HR, IT Helpdesk, Procurement, Onboarding) are all RAG-only. The "not what we want" feedback is likely not about missing fields -- it is about the form not reflecting the VISION of what agents will become. The gap analysis documents the vision (Bloomberg, CapIQ, Oracle Fusion) but does not acknowledge that zero A2A agents exist today. The authoring surface is being designed for agents that do not exist yet, while the 4 agents that DO exist are simple enough to author in the current form. This is a sequencing problem, not just a UI problem.

**Recommendation**: The analysis should explicitly address the temporal mismatch. The 7-section form should be designed for progressive revelation based on auth_mode selection. When auth_mode = "None", sections 3 (Authentication), 4 (Plan gate -- typically only used for premium A2A agents), and the tool assignment subsection of 5 should collapse to zero-height with a one-line summary ("No authentication required. No tools assigned."). This makes the RAG-only authoring experience 3 sections (Identity, Prompt, Guardrails) while keeping the full 7-section surface available when auth_mode flips to "Tenant Credentials."

---

## Finding 3: UX Design Critique

### 3a: Full-Page Overlay Justification

**Severity**: HIGH (architecture precedent risk)

The UX spec makes a significant departure from the established Platform Admin pattern: every other PA detail view (Tenants, LLM Profiles, Tool Catalog) uses a slide-in panel. The Agent Template Studio introduces a full-page overlay that collapses the sidebar to icon-only mode. The justification is that "a 560px slide-in cannot contain [7 sections] without extreme scrolling."

**Counter-argument**: The slide-in panel width is configurable. The existing pattern in the Obsidian Intelligence design system supports resizable sidebars (180px-25vw). The analysis could have proposed a wider slide-in (720px or 800px) rather than introducing an entirely new layout pattern. A full-page overlay:

- Breaks the spatial relationship between the template list table and the editing surface (admin loses visual context of where they came from)
- Creates a modal-like experience for what is an iterative editing workflow (draft/edit/publish)
- Sets a precedent that any complex configuration surface can justify a full-page takeover, eroding the consistency of the PA layout

**The UX spec's own rationale undermines itself**: It says "templates are iterated on (draft/edit/publish cycle) -- wizards are for one-time flows," then proposes a full-page overlay that feels more like a "dedicated application" than an "in-context editing panel." The accordion-in-a-slide-in pattern would maintain spatial context while supporting all 7 sections.

**Recommendation**: Test the 7-section accordion in an 800px slide-in panel before committing to the full-page overlay. If the content genuinely does not fit at 800px (the system prompt textarea, variable schema table, and credential schema table need horizontal space), then the overlay is justified. But this should be a prototype-driven decision, not an assumption.

### 3b: Seven-Section Accordion Mental Model

**Severity**: MEDIUM (usability risk)

The 7-section accordion maps to the 7 configuration dimensions, which is logical from a data model perspective. But it does not match the mental model of a platform admin building an agent. The admin's mental model is closer to:

1. **What is it?** (Identity + Prompt -- who am I building?)
2. **What can it access?** (KB + Tools + Credentials -- what data sources?)
3. **Who can use it?** (Plan gate + Access control -- who sees it?)
4. **What are the rules?** (Guardrails + Citation mode -- what boundaries?)
5. **Ship it** (Version + Publish)

This is 5 conceptual groups, not 7. The current 7-section layout fragments related concepts (KB recommendations in section 5, but guardrail confidence threshold in section 6 -- both affect response quality). The credential schema (section 3) is logically tied to tool assignments (section 5) because credentials exist to authenticate tool access.

**Recommendation**: Consider a 5-group accordion that maps to the admin's mental model rather than the data model. This does not change the data captured; it changes the grouping:

| Group | Sections Merged | Rationale |
|-------|----------------|-----------|
| Identity | S1 (Identity) + S2 (System Prompt) | Both define "what this agent is" |
| Data Access | S3 (Auth) + S5 (KB/Tools) | Auth exists to enable tool access; KB and tools are both data sources |
| Distribution | S4 (Plan + Capabilities) | Who gets access |
| Guardrails | S6 (Guardrails) | Behavioral boundaries |
| Lifecycle | S7 (Version History) | Publishing and versioning |

This is a product design question that should be tested with actual platform admins before committing to a layout.

### 3c: Test Harness Complexity

**Severity**: LOW (implementation risk, not conceptual)

The test harness as a 400px slide-in that overlays the studio content is reasonable for the full-page overlay layout. It would be problematic in the slide-in-panel layout (a slide-in opening from within another slide-in creates z-index confusion and spatial disorientation).

The test harness itself is well-specified. One gap: there is no affordance for testing guardrail BYPASS. The admin can test a guardrail trigger ("What's the CEO's salary?" triggers salary_disclosure block), but there is no way to test whether a carefully worded query can evade the regex pattern. A "Guardrail Stress Test" mode that automatically generates adversarial variants of guardrail patterns would significantly increase the value of the test harness. This is a Phase 2 feature, not a blocker, but should be documented as a future enhancement.

---

## Finding 4: Scope and Prioritization Critique

**Severity**: HIGH (resource allocation risk)

The gap analysis recommends redesigning both PA and TA surfaces simultaneously, with the PA surface as Priority 1 and the TA deployment wizard as Priority 2. The implementation timeline proposes 6 weeks for both.

**The prioritization is backwards for revenue impact.** The PA template authoring form is used by a small team (1-3 platform admins). The TA deployment wizard is used by every tenant admin who adopts an agent. If the goal is to demonstrate agent value to paying customers, the TA deployment wizard should ship first -- even with manually authored templates (platform admins can use direct database edits or a basic form to create templates in the interim).

**More critically: the 4 seed templates already exist in the codebase.** The gap analysis correctly identifies this fact but does not follow the implication. Those 4 templates do not need to be authored through the new PA form -- they are code-defined. What is missing is the TA surface to deploy them. A tenant admin today cannot bind KBs, set access control, or configure rate limits for those seed templates. That is the immediate revenue blocker.

**Recommended resequencing:**

```
Week 1-2: Backend Phase A (FP-01 guardrails, FP-02 access control, FP-03 KB bindings)
Week 2-4: TA deployment wizard for existing seed templates (Flow 3)
Week 3-5: TA agent management cards + configure panel
Week 5-7: PA template authoring form redesign (Flow 1)
Week 7-8: PA publish/version/deprecate workflows (Flow 2, 2B, 2C)
```

This delivers tenant-facing value 2-3 weeks earlier while the PA surface is built in parallel. The seed templates provide the supply; the TA wizard provides the adoption mechanism.

---

## Finding 5: Missing Dimensions

### 5a: Agent Identity in the Chat UI

**Severity**: HIGH (end-user experience gap)

Neither document addresses what end users see when they interact with an agent. The analysis focuses entirely on the admin authoring and deployment surfaces. But the agent's identity in the chat UI -- icon, name, description, behavioral tone -- is the surface that matters most to the 95% of users who never see an admin panel.

Questions not answered:
- Where does the agent appear in the end-user chat UI? (The mode selector in the input bar? A sidebar agent list? Both?)
- How does the icon from the 6-option picker render in the chat message area? (The AI response anatomy in the design system specifies "AGENT . MODE" in the meta row -- does the agent icon appear there?)
- Can tenant admins customize the display name end users see (different from the template name)?
- Does the agent have a "greeting" message when selected? (The chat empty state has an agent icon and greeting -- is this configurable per agent?)
- When an agent is guardrail-blocked, what does the end user see? (The analysis says "blocked responses are replaced with safe fallback messages" but the fallback message authoring is in the PA guardrail section -- does the TA have visibility into what their users will see?)

This is not a "nice to have." Agent identity in the chat UI is the primary surface through which all product value flows. The analysis should include a section on "Agent Presentation to End Users" that connects the admin-authored identity fields to the chat UI rendering.

### 5b: Agent Performance Feedback Loop

**Severity**: HIGH (operational gap)

The gap analysis mentions FP-06 (version-bump workflow) but does not address how a platform admin knows whether a template is performing well AFTER tenants deploy it.

Missing feedback mechanisms:
- Template-level aggregate metrics (satisfaction score, guardrail violation rate, average confidence) across all tenant instances -- visible only as aggregates, not per-tenant data
- Template comparison (which of the 4 seed templates has the highest satisfaction? which has the most guardrail violations?)
- Degradation alerts (template's aggregate confidence dropped 15% this week -- investigate)
- Tenant adoption funnel (how many tenants viewed the template in catalog vs. started deployment vs. completed deployment vs. active usage after 7 days?)

Without this feedback, platform admins are authoring templates blind. They publish v1.0.0 and have no data-driven signal to inform v1.1.0. The Instances tab in the UX spec shows tenant name, version, status, and usage count -- but usage count alone does not tell you if the agent is GOOD.

**Recommendation**: Add a "Performance" tab (or merge into the Instances tab) that shows template-level aggregated metrics. This does not require per-tenant data exposure -- it can be computed from anonymized query logs.

### 5c: HAR (Hosted Agent Registry) Scoping

**Severity**: LOW (scope boundary is correct)

The analysis correctly scopes Agent Studio as separate from the Hosted Agent Registry. The HAR is about cross-tenant agent discovery and A2A transaction brokering (doc 32). Agent Studio is about authoring and deploying agents within the platform. These are distinct concerns with different timelines (HAR is Phase 2+).

One gap: there is no mention of how a template created in Agent Studio eventually gets listed in the HAR, if ever. The HAR requires KYB verification, trust levels, and transaction taxonomy -- none of which exist in the template data model. If the long-term vision is that platform-curated templates eventually become HAR-listed agents, the template data model should include extensibility points (even if empty today) for HAR metadata. If the vision is that HAR agents are a completely separate entity type, that should be stated explicitly.

### 5d: Tenant-to-Platform Template Promotion

**Severity**: MEDIUM (missing product decision)

Neither document addresses whether a tenant admin's custom agent can be "promoted" to a platform template. This is a significant product question:

- If yes: the custom agent studio needs a "Submit to Platform" action, the platform admin needs an approval workflow, and the data model needs a migration path from instance to template (adding versioning, plan gates, variable extraction from the literal prompt).
- If no: this should be stated explicitly, with the rationale. (Likely rationale: tenant custom agents contain tenant-specific KB bindings and access rules that do not generalize. Platform templates are designed for reuse; tenant agents are designed for specificity.)

**Recommendation**: Add a "Design Decision" section to the gap analysis stating: "Tenant custom agents are not promotable to platform templates. The two entity types serve different purposes. A platform admin who sees a successful pattern in a tenant's custom agent should recreate it as a new template, not promote the instance."

---

## Finding 6: Failure Point Priority Assessment

**Severity**: MEDIUM (priority ordering is mostly correct but missing one critical item)

The 13 failure points are well-identified. The CRITICAL tier (FP-01 through FP-04) is correctly ordered by impact. FP-01 (guardrails not enforced) is correctly identified as the highest-risk item -- a financial services agent providing unfiltered investment advice is a regulatory liability.

**However, there is a missing CRITICAL failure point that should be FP-00:**

**FP-00: Agent instance cache invalidation is not implemented.**

The architecture doc (33, Section 5) specifies that agent instances are cached in Redis with a 5-minute TTL and invalidated via pub/sub on configuration changes. But the gap analysis does not verify whether this cache invalidation exists. If a tenant admin changes access rules (restricting an agent to analysts only) and the old cache persists for 5 minutes, users who should be denied access continue to use the agent. For guardrail changes, this is even worse: a platform admin fixes a guardrail and publishes a new version, but the runtime continues using the cached version without the fix for up to 5 minutes.

This is not speculative -- cache invalidation bugs are the #1 source of "my change isn't working" issues in production. The gap analysis should verify that:
1. Redis pub/sub is wired for agent instance cache keys
2. Cache invalidation triggers on ALL mutation paths (deploy, update access rules, update guardrails, pause, archive)
3. The 5-minute TTL is a fallback, not the primary invalidation mechanism

**Additionally, FP-08 (prompt injection in tenant custom agents) should be elevated to CRITICAL, not HIGH.** The analysis rates it "Medium likelihood" because it "requires malicious or careless tenant admin." This underestimates the risk. A tenant admin does not need to be malicious -- they can copy-paste a prompt from the internet that contains injection patterns. The SystemPromptValidator is a security boundary, not a convenience feature. Without it, a tenant admin's custom agent could instruct the LLM to ignore guardrails, which renders FP-01's fix (output filter) partially ineffective.

---

## Finding 7: The RAG-Only vs. A2A Conceptual Mismatch

**Severity**: CRITICAL (product architecture question)

This is the hardest question and the analysis does not address it.

The 4 seed templates (HR, IT Helpdesk, Procurement, Onboarding) are RAG-only agents. They take a system prompt and a set of KB bindings and synthesize answers from retrieved documents. They have no external credentials, no tool invocations, no A2A capabilities. They are, functionally, configured chatbots with guardrails.

The Agent Studio design is built for Bloomberg/CapIQ-style agents that authenticate to external APIs, invoke MCP tools, handle credential rotation, and operate in regulated environments with strict guardrails. These are fundamentally different entities:

| Dimension | RAG-Only Agent | A2A Agent |
|-----------|---------------|-----------|
| Data source | Tenant KBs (internal documents) | External APIs (Bloomberg, CapIQ) |
| Authentication | None | OAuth2, API keys, BSSO |
| Tools | None or optional (Jira reader) | Core to function |
| Guardrails | Nice-to-have (compliance) | Mandatory (regulatory) |
| Credential lifecycle | N/A | Daily health checks, rotation |
| Failure mode | Low-confidence answer | API error, credential expiry |
| Plan gate | Typically none (baseline) | Typically Professional+ |

The proposed design treats these as the same entity with optional fields. This is architecturally clean but experientially confusing. A platform admin creating the HR Policy Advisor fills 3 of 7 sections and leaves 4 blank. That is a form completion rate of 43%. It communicates "you are using this wrong" or "this is overbuilt for what you need."

**Three options:**

**Option A: Uniform model (current proposal).** One form, 7 sections, progressive disclosure via auth_mode. Simple to build, simple to maintain, but the RAG-only experience feels heavy.

**Option B: Two explicit types.** "Create RAG Agent" and "Create A2A Agent" as separate entry points. RAG agents get a 4-section form (Identity, Prompt, KB Recommendations, Guardrails). A2A agents get the full 7-section form. Data model is the same; the UI is differentiated. Risk: if a RAG agent later needs tool assignments, the admin must "upgrade" it to A2A, which is a confusing operation.

**Option C: Progressive complexity (recommended).** One form, but the initial state shows only Identity, System Prompt, and Guardrails. When the admin selects auth_mode != "None" or assigns tools, the form dynamically reveals additional sections with a transition animation and a contextual explanation ("Adding credentials unlocks external data source integration. Configure the credential schema below."). This preserves the uniform data model while providing a lightweight experience for simple agents and a full experience for complex ones.

**Recommendation**: The analysis MUST take a position on this question and document the trade-offs. Option C is recommended because it preserves architectural simplicity while solving the experiential mismatch. The UX spec should be updated to specify the progressive reveal behavior.

---

## Gaps That Must Be Added Before Implementation

| # | Gap | Where to Add | Blocking? |
|---|-----|-------------|-----------|
| G1 | Agent identity in end-user chat UI (icon, name, greeting, guardrail fallback message visibility) | New section in gap analysis + new section in UX spec | YES -- end-user experience is the primary value surface |
| G2 | Progressive complexity for RAG-only vs. A2A agent authoring (Option C or explicit decision on uniform model) | UX spec Section 2, new decision item | YES -- affects form architecture |
| G3 | Template performance metrics tab (aggregate satisfaction, confidence, violation rate) | UX spec Section 3, new tab spec | NO -- can ship in follow-up sprint |
| G4 | Additive tenant guardrails on top of template guardrails | Gap analysis, architecture decision | NO -- can defer, but must document the "no" decision |
| G5 | Cache invalidation verification (FP-00) | Gap analysis, new CRITICAL failure point | YES -- runtime correctness depends on it |
| G6 | Tenant-to-platform promotion decision (explicit "no" with rationale) | Gap analysis, design decision section | NO -- documentation only |
| G7 | FP-08 elevation to CRITICAL (SystemPromptValidator as security boundary) | Gap analysis, re-prioritize | YES -- security classification |
| G8 | Naming disambiguation ("Studio" for PA only; different name for TA custom agent builder) | UX spec, terminology section | NO -- cosmetic but important for clarity |
| G9 | Full-page overlay vs. wide slide-in prototype test | UX spec Section 2.1, add decision gate | YES -- blocks component architecture |

---

## Final Recommendation

The gap analysis (doc 01) is **strong on technical completeness** -- the 7-dimension framework, the current-vs-vision gap table, and the 13 failure points are thorough and evidence-based. It is the best articulation of the agent concept model in the mingai documentation.

The UX design spec (doc 02) is **detailed and design-system-compliant** but makes two unforced errors: the full-page overlay precedent break and the uniform 7-section form for both RAG-only and A2A agents.

**Before proceeding to /todos, the following changes are required:**

1. **Add G1 (agent identity in chat UI)** to the gap analysis and UX spec. Without this, the analysis describes how admins build agents but not how users experience them.

2. **Resolve G2 (progressive complexity)** with an explicit design decision. The analysis must state whether the form is uniform, type-split, or progressively revealed. This affects component architecture.

3. **Add G5 (cache invalidation as FP-00)** to the failure points. This is a runtime correctness issue that affects every other fix.

4. **Elevate G7 (FP-08 to CRITICAL)**. SystemPromptValidator is a security boundary, not a convenience feature.

5. **Resolve G9 (overlay vs. wide slide-in)** with a prototype test before committing to the full-page overlay. If prototyping is not feasible before /todos, document it as a Sprint 1 deliverable: "Prototype both layouts; select based on admin feedback."

6. **Resequence implementation** to prioritize TA deployment wizard before PA authoring redesign (Finding 4). The seed templates are the immediate supply; the TA wizard is the immediate revenue unblock.

Items G3, G4, G6, and G8 can be addressed in the /todos planning phase without blocking the analysis.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-21
**Review Method**: Adversarial critique across product value, implementation risk, UX architecture, and missing dimensions. Cross-referenced against architecture doc (33), user flows (23), and MEMORY.md project context.
