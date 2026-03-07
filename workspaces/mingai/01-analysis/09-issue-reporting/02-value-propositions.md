# 09-02 — Issue Reporting: Value Propositions

**Date**: 2026-03-05

---

## Framing

A value proposition answers: "What problem does this solve for which customer?"
A unique selling point answers: "Why can ONLY we solve it this way?"

Both matter, but they must not be confused. This document focuses on value propositions.

---

## 1. Primary Value Proposition

### For End Users (Consumers)

**"Report issues once and know they're being handled — without chasing anyone."**

Today, when an enterprise SaaS user encounters a bug, they face a choice: ignore it, email support (and hear nothing), or accept the broken experience. The cost is invisible to the vendor but real to the user: frustration, reduced trust, workaround behaviors, and eventual churn.

Our solution makes reporting effortless (one click, automatic context) and closes the loop (acknowledgment, SLA, progress updates). Users feel heard and respected.

### For Engineering Teams (Producers)

**"Turn raw user complaints into actionable, reproduction-ready GitHub issues without manual triage."**

Bug reports from users are typically incomplete: "it doesn't work" with no reproduction steps. Engineers waste hours asking follow-up questions or reproducing issues from scratch. Our AI agent automatically enriches reports with session context (last query, model, data sources, console errors, network failures) and generates structured reproduction steps. Engineers can act immediately.

### For Platform/Product Teams (Partners)

**"Close the quality feedback loop across your entire user base systematically."**

Without a structured feedback mechanism, product teams rely on anecdote, support tickets, and NPS surveys — all lagging indicators. Our system creates a real-time quality signal that flows directly into the engineering backlog, prioritized by AI severity scoring.

---

## 2. Value Propositions by Stakeholder

### 2.1 End User Value Propositions

| Problem                                                         | How We Solve It                                            | Measurable Outcome                                        |
| --------------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------- |
| "I reported a bug and never heard back"                         | Automated acknowledgment + SLA commitment within 5 minutes | 100% of reports acknowledged                              |
| "Reporting is more effort than it's worth"                      | One-click with automatic context capture                   | <60 seconds to report                                     |
| "I don't know if my feedback matters"                           | Real-time status updates as fix progresses                 | Users see GitHub PR status without knowing GitHub         |
| "I had to describe the exact state to reproduce"                | Screenshot + auto-captured session context                 | No need to recreate context manually                      |
| "I reported the same bug others reported, and nothing happened" | Duplicate consolidation shows upvote count                 | User knows their report joined others for higher priority |

### 2.2 Engineering Team Value Propositions

| Problem                                                  | How We Solve It                                                 | Measurable Outcome                                |
| -------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------- |
| "User reports are incomplete and require back-and-forth" | AI-enriched reports with session context                        | 80%+ reports are reproduction-ready on submission |
| "Triage takes time that could go to fixing"              | Automated severity scoring, categorization, duplicate detection | Triage time reduced from 30 min to <5 min         |
| "Same bug reported 50 times, clutters backlog"           | Semantic duplicate detection across all tenants                 | 1 canonical issue per bug, not 50 duplicates      |
| "I don't know which tenant or query triggered this"      | Full session context in every GitHub issue                      | Zero follow-up questions for P0-P2 bugs           |
| "Managing status communication to reporters is overhead" | Automated notifications via GitHub webhook                      | Zero manual status update emails                  |

### 2.3 Platform/Product Team Value Propositions

| Problem                                                     | How We Solve It                                                        | Measurable Outcome                       |
| ----------------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------- |
| "No signal on what's breaking for which tenant"             | Issue dashboard by tenant, category, severity                          | Clear heatmap of quality by tenant       |
| "Bug priority is set by whoever shouts loudest"             | AI severity scoring + report volume                                    | Objective, data-driven prioritization    |
| "We discover bugs via customer complaints, not proactively" | Real-time issue stream with automatic categorization                   | Shift from reactive to proactive quality |
| "We have no data on recurring pain points"                  | Issue analytics dashboard: top bugs, time to resolution, SLA adherence | Quantitative quality metrics             |

---

## 3. Business Value Propositions

### 3.1 Churn Reduction

**Problem**: Enterprise SaaS churn is driven 40-60% by unresolved quality issues. Users stop using a tool that frustrates them but doesn't acknowledge their pain.

**Mechanism**: Closed feedback loop creates the perception (and reality) of responsiveness. Studies show customers who have a complaint resolved satisfactorily are MORE loyal than customers who never had a complaint.

**Estimate**: If 10% of users who would churn stay because of effective issue resolution, and average customer LTV is $50K, retaining 5 customers per year from a 500-user deployment = $250K in retained revenue.

### 3.2 Support Ticket Deflection

**Problem**: Unhandled bugs generate support tickets. Each support ticket costs $25-$50 to handle (industry benchmark). A 100-user SaaS with 200 bug-related support tickets/year = $5K-$10K in support costs.

**Mechanism**: Structured issue reporting with status visibility reduces "is anyone looking at this?" follow-up tickets by 60-80%.

### 3.3 Engineering Efficiency

**Problem**: A P2 bug takes on average:

- 60 minutes of developer time to reproduce from a raw user report
- 30 minutes of triage/prioritization meetings
- 15 minutes of follow-up communication

**With our system**:

- 5 minutes triage (AI pre-classifies)
- 10 minutes reproduction (context already provided)
- 0 minutes communication (automated)

**Savings**: ~90 minutes per bug × 50 bugs/month = 75 hours/month recovered.

### 3.4 Platform Stickiness (for mingai as SaaS)

When issue reporting is native to mingai, the customer's entire issue history, patterns, and engineering workflow is embedded in the platform. This data is non-portable and creates switching cost. A customer who switches to a competitor loses their issue history, triage patterns, and notification setup.

---

## 4. Network Effect Potential

This feature exhibits modest network effects:

**Within-tenant network**: More users reporting → more duplicates detected → higher priority for widely-impactful bugs → faster resolution for all users.

**Cross-tenant network**: More tenants using → more issue embeddings → better duplicate detection → better prioritization across the platform. A P2 bug affecting tenant A that manifests differently for tenant B can be correlated and fixed once for both.

**Feedback loop as quality flywheel**: Higher issue report volume → better prioritization → faster resolution → more user trust → more reporting.

---

## 5. The 80/15/5 Value Lens

Per the product design principles:

**80% reusable/agnostic**:

- Screenshot capture and annotation widget
- AI triage agent (severity, category, duplicate detection)
- GitHub/GitLab issue creation API
- SLA calculation and commitment engine
- Notification system (in-app, email, webhook)
- Issue dashboard and analytics
- Rate limiting and abuse prevention

**15% client-specific (but self-service)**:

- Custom severity SLA definitions per tenant
- Custom issue categories (tenant can add their own)
- Custom notification recipients (e.g., notify Slack channel instead of email)
- GitHub repository target (tenant can specify their own repo)
- Custom fields in issue template

**5% customization**:

- Custom branding on reporter widget
- Integration with non-GitHub systems (GitLab, Jira, Linear) per enterprise requirement
- Custom escalation rules (e.g., "P0 always pages on-call engineer")

This 80/15/5 split means this feature can be productized across any enterprise SaaS platform using our infrastructure, not just mingai — a significant platform extension opportunity.
