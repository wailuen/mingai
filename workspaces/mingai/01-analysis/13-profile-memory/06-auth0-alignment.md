# 13-06 — Auth0 Alignment: OrgContextSource Simplification

**Status**: Addendum to `04-implementation-alignment.md`
**Date**: 2026-03-07
**Supersedes**: OrgContextSource abstraction design in `04-implementation-alignment.md` §Sprint 4 only
**References**: `01-research/38-auth0-sso-architecture.md`, `01-research/39-teams-collaboration-architecture.md`

---

## 1. Decision Summary

Auth0 is a hard product dependency for all mingai tenants. Every SSO provider — Azure AD, Okta, Google Workspace, SAML, username/password — federates through Auth0. mingai receives a single normalized OIDC JWT regardless of the upstream identity provider.

This has a direct structural consequence for the Profile & Memory system: the 3-source `OrgContextSource` abstraction specified in `04-implementation-alignment.md` is eliminated. There is no longer a need to branch by upstream provider at runtime.

**Changes in force:**

- `AzureADOrgContextSource`, `OktaOrgContextSource`, `GenericSAMLOrgContextSource` — deleted
- `Auth0OrgContextSource` — single replacement implementation; JWT-first path with Management API fallback
- `OrgContextSource` abstract interface — retained (correct design; single implementation does not eliminate the value of the interface)
- Full technical specification for Auth0 SSO integration: `01-research/38-auth0-sso-architecture.md`

---

## 2. What Changes in the Profile & Memory System

### Changed

| Component                             | Before                                                        | After                          |
| ------------------------------------- | ------------------------------------------------------------- | ------------------------------ |
| `OrgContextSource` abstract interface | Defined in `04-implementation-alignment.md`                   | Unchanged — retained           |
| `AzureADOrgContextSource`             | Planned implementation                                        | Deleted                        |
| `OktaOrgContextSource`                | Planned implementation                                        | Deleted                        |
| `GenericSAMLOrgContextSource`         | Planned implementation                                        | Deleted                        |
| `Auth0OrgContextSource`               | Not in scope                                                  | New — replaces all three       |
| Provider selection logic              | Tenant `sso_provider` field drove which source to instantiate | Removed — single source always |

### Unchanged

- Database tables: `user_profiles`, `memory_notes`, `profile_learning_events` — no schema changes
- `ProfileLearningService` — no changes
- `WorkingMemoryService` — no changes
- `SystemPromptBuilder` — no changes
- Org Context Redis cache: key `{tenant_id}:org_context:{user_id}`, TTL 24h — unchanged. The cache is now more critical than ever: it is the primary rate-limit shield against Auth0 Management API call volume.

### Sprint 4 impact

3 source implementations collapse to 1. Estimated saving: ~6h of implementation and test time.

---

## 3. Auth0 JWT Claims for Org Context

`Auth0OrgContextSource` follows a JWT-first, Management API fallback pattern.

**JWT fast path** — reads the following claims directly from the decoded JWT if present:

| JWT Claim      | Maps to Org Context Field |
| -------------- | ------------------------- |
| `job_title`    | `job_title`               |
| `department`   | `department`              |
| `country`      | `country`                 |
| `company`      | `company`                 |
| `manager_name` | `manager_name`            |

These claims are injected by a tenant-configured Auth0 Action (post-login hook). They are optional — not all tenants will configure the Action.

**Management API fallback** — when JWT claims are absent or incomplete, `Auth0OrgContextSource` calls the Auth0 Management API to retrieve `app_metadata` for the user. The field names in `app_metadata` are not standardized across tenants; per-tenant field mapping resolves this (see §4).

**Resolution order for each field:**

1. JWT claim (present and non-empty) → use directly
2. JWT claim absent → `app_metadata` key via tenant field mapping
3. Both absent → field omitted from `OrgContextData` (graceful degradation, not an error)

---

## 4. Per-Tenant Field Mapping

**Problem**: `app_metadata` key names vary across tenants — `dept` vs `department` vs `ou`, `title` vs `job_title`, etc.

**Solution**: `org_context_field_mapping` JSONB column in `tenant_settings`.

**Default** (applied when no custom mapping is configured):

```json
{
  "job_title": "job_title",
  "department": "department",
  "country": "country",
  "company": "company",
  "manager_name": "manager_name"
}
```

**Custom example** (tenant using Azure AD app_metadata passthrough with non-standard keys):

```json
{
  "job_title": "title",
  "department": "ou",
  "country": "physicalDeliveryOfficeName",
  "company": "company",
  "manager_name": "manager"
}
```

**Configuration surface**: Tenant Admin > Settings > SSO > Org Context Mapping. Tenant admins specify the right-hand side (the actual `app_metadata` key name). Left-hand side (the mingai canonical field name) is fixed and non-editable.

---

## 5. Auth0 Group Claims and Team Sync

Auth0 JWT `groups` claim carries the user's group memberships as of login time. On each login event, `Auth0OrgContextSource` triggers a team membership sync against this claim.

This is a distinct concern from Org Context and is specified in full in:

- `01-research/39-teams-collaboration-architecture.md`
- `01-analysis/15-teams-collaboration/` (when created)

Scope of this addendum: the group claim sync is noted here for completeness. Implementation details live in the Teams & Collaboration track.

---

## 6. Updated Sprint 4 Task List

The following replaces the Sprint 4 task list in `04-implementation-alignment.md` for the OrgContextSource section only.

| Task                                                                    | Effort | Notes                                                                   |
| ----------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------- |
| Create `OrgContextData` normalized schema                               | 1h     | No change from original plan                                            |
| Create `OrgContextSource` abstract interface                            | 1h     | Simplified — single implementation, interface retained for correctness  |
| Implement `Auth0OrgContextSource` (JWT-first + Management API fallback) | 4h     | Replaces the 3-source design                                            |
| Implement per-tenant field mapping config + API                         | 2h     | `org_context_field_mapping` JSONB in `tenant_settings`                  |
| Tenant Admin UI: SSO field mapping configuration                        | 2h     | Settings > SSO > Org Context Mapping                                    |
| Auth0 Management API client setup                                       | 1h     | M2M credentials in `.env`; scopes: `read:users`, `read:user_idp_tokens` |
| Unit tests (10 tests)                                                   | 3h     | JWT path + Management API path + field mapping logic + cache behaviour  |

**Sprint 4 total: ~14h** (vs original ~16h — ~6h removed for 3 source implementations, ~4h added for field mapping and Auth0 Management API client)

---

## 7. Risks Introduced

| Risk ID | Risk                                                             | Severity | Mitigation                                                                                                                                                                                                                                                                                           |
| ------- | ---------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R-A01   | Auth0 Management API rate limits (burst traffic at peak login)   | High     | Redis cache is mandatory — 24h TTL means Management API called at most once per user per day. Cache-aside pattern; do not call Management API if cache hit exists.                                                                                                                                   |
| R-A02   | JWT claims absent because tenant has not configured Auth0 Action | Medium   | Management API fallback handles this path. No user-visible degradation. Document the Auth0 Action setup as a recommended (not required) configuration step in Tenant Admin onboarding.                                                                                                               |
| R-A03   | `app_metadata` field naming inconsistency across tenants         | Medium   | Per-tenant field mapping config (§4) resolves at runtime. Default mapping covers standard key names and will work for most tenants without manual configuration.                                                                                                                                     |
| R-A04   | Auth0 outage affects org context availability                    | Low      | Cached data survives 24h and covers the outage window for active users. If cache miss occurs during Auth0 outage, org context layer is gracefully skipped — `OrgContextData` returned as empty, `SystemPromptBuilder` omits the layer without error. Response quality degrades slightly; no failure. |

---

## 8. Relationship to Other Documents

| Document                                             | Relationship                                                                                                                                                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `13-04 — implementation-alignment.md`                | This addendum supersedes the OrgContextSource multi-source design in Sprint 4. All other content in `13-04` remains valid.                                                |
| `01-research/38-auth0-sso-architecture.md`           | Full technical specification for Auth0 integration across mingai. This addendum draws the org context implications from that spec.                                        |
| `01-research/39-teams-collaboration-architecture.md` | Group claims and team sync (§5 above). Out of scope for this addendum.                                                                                                    |
| `13-05 — red-team-critique.md`                       | No new CRITICAL risks introduced. R-A01 (rate limits) is captured in the risk table above at High severity. Existing GDPR risks (R01, R04) are unaffected by this change. |
| `02-plans/08-profile-memory-plan.md`                 | Sprint 4 task list should be updated to reflect this addendum before Sprint 4 begins.                                                                                     |
