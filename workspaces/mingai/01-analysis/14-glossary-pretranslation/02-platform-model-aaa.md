# 14-02 — Platform Model & AAA: Glossary Pre-Translation

## 1. Platform Model Analysis

Glossary Pre-Translation is not a standalone feature — it is an infrastructure layer that makes the mingai platform more valuable as a multi-sided marketplace between knowledge producers and knowledge consumers.

### 1.1 Platform Roles

**Producers: Tenant Admins and Domain Experts**
Producers create and maintain glossary terms. They are typically:

- HR administrators managing employee-facing terminology
- IT leads defining system and process acronyms
- Compliance officers controlling regulatory abbreviation standards
- Subject-matter experts contributing domain vocabulary

Producers do not directly benefit from query expansion themselves (they know what the acronyms mean). Their incentive to contribute is indirect: better responses for their end users means fewer escalations, fewer "the AI doesn't understand our company" complaints, and faster onboarding of new employees. The platform must surface this indirect value (via analytics showing "X queries expanded using your glossary this month").

**Consumers: End Users**
Consumers are the employees querying the RAG system. They use acronyms naturally because that is how their colleagues communicate. They do not know — and should not need to know — that the LLM is a general-purpose model unfamiliar with internal vocabulary.

The quality delta between a naive user ("What is the LTV limit?") and an expert user ("What is the Loan-to-Value ratio limit?") is eliminated by pre-translation. All users converge to expert-level query quality without training or awareness.

**Partners: The RAG Pipeline and LLM**
The downstream pipeline (embedding generator, vector search, LLM synthesis) is the partner that benefits from the pre-translation work done upstream. The RAG pipeline receives queries with higher semantic clarity. The LLM receives queries where disambiguation is already resolved. Neither partner needs modification — the value is delivered through the interface contract (the query string).

This is the correct platform design: producers enrich the platform's knowledge layer, the platform transforms that knowledge into query-time intelligence, and consumers benefit transparently.

### 1.2 Network Value Creation

The glossary creates compounding platform value through a reinforcement loop:

```
More tenants adopt platform
  → Each tenant builds a glossary
    → Glossary quality improves through use and iteration
      → Response quality improves
        → More users adopt the platform
          → More feedback signals for analytics
            → Tenant admins see which terms fire most
              → Admins prioritise those terms
                → Glossary quality improves further
```

This loop is tenant-internal (not cross-tenant — glossaries are isolated). The network effect is within each tenant organisation, not across the platform as a whole. This is an important distinction: the glossary does not create a cross-tenant network effect, only a within-tenant compounding effect.

Cross-tenant network effects require a different mechanism (e.g., anonymised industry-template glossaries seeded from platform-aggregated patterns — a Phase 3+ concept).

### 1.3 Switching Costs

Each glossary term represents accumulated domain knowledge that does not exist anywhere else in a machine-readable, query-integrated form. A tenant with 300 curated terms, 5,000 query-expansion events per month, and analytics dashboards showing which terms drive engagement has built a proprietary layer on top of mingai.

Migrating to a competitor requires:

1. Exporting the glossary (if possible — terms may be in a format incompatible with competitors)
2. Rebuilding any integration with the query pipeline (competitors likely don't have this feature)
3. Re-validating term accuracy in the new context
4. Losing expansion analytics history

This is a genuine switching cost moat, not an artificial lock-in.

---

## 2. Transaction Dynamics

### 2.1 The Core Transaction

The core platform transaction is:

> User submits a query → Platform retrieves relevant context → LLM synthesises an accurate, domain-appropriate response → User acts on the response

This transaction succeeds when:

- The query accurately represents the user's intent
- The retrieved context is relevant to the query
- The LLM correctly interprets domain-specific terms in both the query and the retrieved context

Pre-translation directly improves transaction success at two of these three conditions:

**Condition 1 (Query accuracy):** The expanded query more accurately represents the user's intent as understood by the LLM. "AWS" alone is ambiguous (Amazon Web Services? Annual Wage Supplement?). "AWS (Annual Wage Supplement)" is unambiguous.

**Condition 3 (LLM interpretation):** The LLM receives the full form as context, reducing the probability that it defaults to a general-knowledge interpretation of the acronym that conflicts with the tenant's domain meaning.

### 2.2 Transaction Failure Modes Addressed

| Failure Mode                                   | Before Pre-Translation                         | After Pre-Translation                              |
| ---------------------------------------------- | ---------------------------------------------- | -------------------------------------------------- |
| LLM interprets acronym as general knowledge    | High probability                               | Low probability (full form forces correct context) |
| LLM asks clarifying question                   | Moderate (for ambiguous acronyms)              | Low (expansion is pre-resolved)                    |
| Retrieved chunks don't match intent            | Moderate (acronym in query, full form in docs) | Reduced (both forms available)                     |
| Response quality varies by user sophistication | Yes (expert vs novice gap)                     | No (equalized by expansion)                        |

### 2.3 Token Economy of the Transaction

The current transaction consumes ~500 tokens of "glossary rent" regardless of whether any glossary terms appear in the query. Pre-translation makes the token cost proportional to actual value: each expansion costs ~4-6 tokens and delivers one unit of disambiguation.

At 10 expansions per query (an extreme case), the expanded query costs ~50 additional tokens — 10x less than the flat glossary injection overhead, while delivering targeted disambiguation rather than blanket context.

---

## 3. AAA Framework

### 3.1 Automate

**Definition:** Remove manual steps that humans currently perform to get a result.

**What is automated:** Users currently must manually spell out acronyms to get quality responses. Power users learn this workaround. New users do not. Pre-translation automates the acronym-to-full-form translation that was previously a manual, invisible tax on query quality.

Additionally, glossary injection required a human-designed system prompt section to be maintained as the glossary grew. Pre-translation automates the context delivery mechanism — no prompt template maintenance required.

**Score: 8/10**

Justification: The automation is complete for matching cases. It removes a genuine manual burden (user education, power-user workarounds, prompt template maintenance). Deduction for cases where automation fails gracefully but silently (false positives, missed terms) — the failure mode is invisible to the user.

### 3.2 Augment

**Definition:** Enhance human capability with AI — the human still drives, the AI assists.

**What is augmented:** The user's natural query is augmented with domain knowledge they already possess but the LLM lacks. The user wrote "AWS" intentionally — they know what it means. Pre-translation augments the query so that the LLM also understands what the user means, without changing the user's intent or overriding their input.

This is a pure augmentation: the user retains authorship of the query, and the platform adds a layer of machine-readable clarification.

**Score: 9/10**

Justification: Near-ideal augmentation. The user's agency is fully preserved (the acronym remains in the query), the platform adds information the LLM needs, and the augmentation is invisible to the user (no friction). Deduction for lack of user visibility — a user cannot see that augmentation occurred, which reduces their ability to understand and correct the system.

### 3.3 Amplify

**Definition:** Scale expert knowledge to all users, without requiring expert availability.

**What is amplified:** Domain experts (compliance officers, IT leads, HR admins) understand the full vocabulary of their domain. Pre-translation captures that expert knowledge in the glossary and amplifies it to every user query — without the expert being present, consulted, or even aware the query was submitted.

This is particularly powerful for onboarding: a new employee who has learned the acronyms but doesn't know to spell them out for the AI immediately benefits from the accumulated glossary knowledge of every domain expert who contributed terms.

**Score: 9/10**

Justification: The amplification loop is strong: one expert's contribution (adding a term to the glossary) benefits every user who ever uses that acronym. The value scales with user count and query volume. Deduction for the fact that amplification quality is entirely dependent on glossary quality — stale or incorrect terms amplify misinformation at scale (see R04 in red team critique).

### 3.4 Summary Table

| AAA Dimension | Score | Key Driver                                         | Key Risk                               |
| ------------- | ----- | -------------------------------------------------- | -------------------------------------- |
| Automate      | 8/10  | Eliminates manual acronym-expansion workarounds    | Invisible failure (false positives)    |
| Augment       | 9/10  | User intent preserved; LLM context enhanced        | User can't see or correct augmentation |
| Amplify       | 9/10  | Expert knowledge scales to all users automatically | Amplifies bad data at scale            |

**Overall AAA Score: 8.7/10** — strong across all three dimensions. The primary risk is that the amplification effect is bidirectional: good glossaries amplify quality, poor glossaries amplify confusion.

---

## 4. Moat Analysis

### 4.1 Data Moat Assessment

**Depth of moat:** MODERATE-STRONG (per-tenant)

Each tenant's glossary is a proprietary dataset that:

- Cannot be recovered from public data (it contains internal, company-specific terminology)
- Grows in value with use (analytics reveal which terms are high-frequency, enabling prioritisation)
- Represents accumulated human curation effort (each term was added, verified, and possibly approved by a domain expert)

A tenant with 500+ terms and 2 years of expansion analytics has built a knowledge asset with no equivalent in any competing platform that lacks this feature.

**Width of moat:** NARROW (platform-level)

The platform does not benefit from a cross-tenant moat today. Each tenant's glossary is isolated. There is no network effect that makes the 500th tenant's glossary better because 499 others have already contributed.

A potential cross-tenant moat exists in Phase 3+: if mingai can offer anonymised industry-template glossaries ("HR terminology starter pack for Singapore-headquartered enterprises"), each new tenant bootstraps faster and the platform becomes the preferred starting point. This is the Salesforce AppExchange model applied to domain glossaries.

### 4.2 Technical Moat Assessment

The pre-translation algorithm is not inherently defensible — a competent engineering team could replicate it in weeks. The moat is in:

1. The tenant's accumulated glossary data (irreproducible without effort)
2. The analytics layer showing which terms drive engagement (requires historical query data)
3. The per-agent scoping configuration (requires understanding of the tenant's agent architecture)

---

## 5. Phase Model

### Phase 1 — Core Pre-Translation (MVP, Q2 2026)

Delivered value:

- Token budget recovery (500 tokens freed per query)
- Prompt injection surface eliminated
- User quality equalization (novice = expert for matched queries)
- Analytics: `glossary_term_matched` events emitted

Platform model activation:

- Producers (admins) maintain the glossary as before; behavior change is entirely on the consumption side
- Consumers benefit immediately on migration
- No UI changes required for Phase 1

AAA activation:

- Automate: full (workarounds eliminated)
- Augment: full (inline expansion active)
- Amplify: full (all users benefit from all glossary contributions)

### Phase 2 — Transparency and Scoping (Q3 2026)

Delivered value:

- User-visible "terms interpreted" indicator in chat UI
- Per-agent glossary scoping (resolve cross-domain acronym conflicts)
- Ambiguity resolution UI for tenant admins
- Expansion analytics dashboard (which terms fire most, which expand correctly)

Platform model activation:

- Analytics creates feedback loop: admins see which terms have high expansion rates → prioritise curation
- Per-agent scoping unlocks multi-persona tenants (HR agent vs IT agent with different glossaries)

### Phase 3 — Industry Templates (2027+)

Delivered value:

- Anonymous industry-level glossary templates seeded from aggregated platform data
- New tenants bootstrap with a starter glossary (reducing time-to-value from weeks to hours)
- Cross-tenant network effect begins to activate

Platform model activation:

- Platform transitions from per-tenant data moat to cross-tenant knowledge network
- Producers now include the platform itself (template generation from aggregated signals)
