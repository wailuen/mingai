# TODO-21: Agent Studio Phase 2 — PA Skills Library Management

**Status**: ACTIVE
**Priority**: HIGH (Phase 2)
**Estimated Effort**: 3 days
**Phase**: Phase 2 — Platform Admin Authoring Studio

---

## Description

Platform admins author, version, publish, and manage the platform-wide skills library. This includes:
- Creating new platform skills (all 3 execution patterns)
- Publishing skill versions with semver + changelog
- Marking skills as mandatory (enforced on all tenant agents)
- Reviewing and promoting tenant-authored skills to the platform library
- Managing skill lifecycle (publish, deprecate, retire)

The PA skills authoring surface reuses the `TenantSkillAuthoringPanel` component pattern from TODO-16 but extends it with platform-specific controls (mandatory flag, plan gating, promotion workflow).

---

## Acceptance Criteria

- [ ] PA navigates to Platform > Skills Library and sees all platform skills with status (draft/published/deprecated)
- [ ] PA can create a new platform skill using all 3 execution patterns (prompt, tool_composing, sequential_pipeline)
- [ ] Sequential pipeline editor: fixed step list; each step: step name, action type (call_tool / run_prompt), config for action type; drag-to-reorder
- [ ] PA can publish a skill with semver version label and required changelog
- [ ] PA can mark a skill as mandatory; confirmation dialog explains impact: "This skill will run on all tenant agents and cannot be removed by tenant admins"
- [ ] PA can deprecate a skill; deprecation notice sent to all tenants who have adopted it
- [ ] PA can view which tenants have adopted each skill (aggregate count — not per-tenant breakdown)
- [ ] Promotion workflow: PA sees "Tenant Submissions" section with tenant-authored skills submitted for promotion (see TODO-16 promotion flow); PA can preview, edit, and promote to platform library
- [ ] Promoted skill appears in platform library with `scope = 'platform'`; original tenant copy remains unchanged
- [ ] Plan gating: PA sets `plan_required` on skill; immediately gates adoption for lower-tier tenants
- [ ] Skill version history: vertical timeline same as template version history
- [ ] Skill test: same test harness pattern as tenant skill test

---

## Backend Changes

### Platform Skills Admin Endpoints

File: `src/backend/app/modules/agents/platform_skills_routes.py`

```python
# Platform skills management (PA only — require platform admin auth)
GET    /platform/skills                      # List all platform skills (all statuses)
POST   /platform/skills                      # Create platform skill (draft)
GET    /platform/skills/{id}                 # Skill detail + versions + adoption stats
PUT    /platform/skills/{id}                 # Update draft skill
POST   /platform/skills/{id}/publish         # Publish with version_label + changelog
POST   /platform/skills/{id}/deprecate       # Deprecate published skill
DELETE /platform/skills/{id}                 # Delete draft skill (only drafts)
POST   /platform/skills/{id}/test            # Test skill (same as tenant test)

# Mandatory flag management
POST   /platform/skills/{id}/mandate         # Set mandatory=true
DELETE /platform/skills/{id}/mandate         # Remove mandatory flag

# Adoption statistics (aggregate only)
GET    /platform/skills/{id}/adoption        # { adoption_count, tenant_count, pinned_count }

# Promotion workflow
GET    /platform/skills/promotions           # List tenant skills submitted for promotion
GET    /platform/skills/promotions/{id}      # Preview tenant skill
POST   /platform/skills/promotions/{id}/approve  # Promote to platform library (copy + set scope=platform)
POST   /platform/skills/promotions/{id}/reject   # Reject with reason
```

### Tenant Skill Promotion Submission

File: `src/backend/app/modules/agents/skills_routes.py` (extend from TODO-16)

Add:
```python
POST /admin/skills/{skill_id}/submit-for-promotion
    # Creates a promotion request record
    # Notifies PA team (via existing notification system)
    # Returns: submission_id
```

New table (migration v053): `skill_promotion_requests`
```sql
CREATE TABLE skill_promotion_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id        UUID NOT NULL REFERENCES skills(id),
    tenant_id       UUID NOT NULL,
    submitted_by    UUID NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by     UUID,
    reviewed_at     TIMESTAMPTZ,
    rejection_reason TEXT,
    platform_skill_id UUID  -- FK to promoted platform skill on approval
);
```

### Deprecation Notification

On skill deprecation:
- Find all `tenant_skill_adoptions` rows for this skill
- Create notification records for each affected tenant's admin users
- Notification: "Platform skill '{name}' has been deprecated. It will continue to function but will not receive updates. Agents using this skill: {count}."

---

## Frontend Changes

### New Page Section

Extend Platform Admin sidebar: Platform > Intelligence > Skills Library

Or add as tab on existing Intelligence section.

### New Components

#### `PASkillsLibraryPage.tsx`

Location: `src/web/app/(platform)/platform/skills/page.tsx`

- Two sub-sections: "Skills Library" (all platform skills) and "Tenant Submissions" (promotion queue)
- Skills Library: tabbed by status (All / Draft / Published / Deprecated) OR status filter chips
- Table: Name, Category, Execution Pattern, Version, Mandatory, Adoptions, Status, Actions

#### `PASkillAuthoringPanel.tsx`

Location: `src/web/app/(platform)/platform/skills/elements/PASkillAuthoringPanel.tsx`

Extends `TenantSkillAuthoringPanel` pattern with PA-only additions:
- Plan gate selector (Section 1 extra field)
- Mandatory toggle (Section 1 extra field) with warning: "⚠ Marking as mandatory runs this skill on all tenant agents"
- Sequential pipeline editor (Section 2 extra pattern option):
  - Step list: add/remove/reorder steps
  - Each step: name, action type radio (Call Tool / Run Prompt), tool selector or prompt textarea
- All 3 execution patterns available (tenants only get 2)

#### `SequentialPipelineEditor.tsx`

Location: `src/web/components/shared/SequentialPipelineEditor.tsx`

- Step list with drag handles
- Each step card: step number badge, step name input, action type radio, conditional fields
- "Add Step" button at bottom
- Step count badge in section header

#### `SkillPromotionReviewPanel.tsx`

Location: `src/web/app/(platform)/platform/skills/elements/SkillPromotionReviewPanel.tsx`

- 480px slide-in from right
- Shows tenant-submitted skill in read-only preview
- Tenant name shown (aggregate data — not a security concern at PA level)
- Edit fields: PA can modify name, description, category before promoting
- [Approve & Promote] button (accent) — promotes to platform library
- [Reject] button (alert) with reason textarea
- Rejection reason sent back to tenant as notification

#### `SkillAdoptionStats.tsx`

Location: `src/web/app/(platform)/platform/skills/elements/SkillAdoptionStats.tsx`

- Shows: Total Adoptions, Tenants Using, Version Pinned %
- All aggregate — no per-tenant breakdown visible to PA
- Used in skill detail panel

### New Hooks

File: `src/web/hooks/usePlatformSkillsAdmin.ts`

```typescript
usePlatformSkillsAdmin()           → { skills, isLoading }
createPlatformSkill(data)          → mutation
updatePlatformSkill(id, data)      → mutation
publishPlatformSkill(id, vl, cl)   → mutation
deprecatePlatformSkill(id)         → mutation
mandateSkill(id)                   → mutation
unmandateSkill(id)                 → mutation
useSkillAdoptionStats(id)          → { stats, isLoading }
usePromotionQueue()                → { submissions, isLoading }
approvePromotion(id)               → mutation
rejectPromotion(id, reason)        → mutation
```

---

## Dependencies

- TODO-13 (DB schema) — skills, skill_versions tables
- TODO-16 (TA Skills) — promotion submission flow built there; reviewed here
- TODO-20 (PA Template Studio) — skills panel reuses SystemPromptEditor

---

## Risk Assessment

- **HIGH**: Mandatory skill enforcement — marking a skill mandatory immediately affects all tenants' agent responses; confirmation dialog must be explicit about impact scope
- **MEDIUM**: Promotion workflow — tenant expects confidentiality; promoted skill must NOT expose which tenant it came from in the platform library description
- **LOW**: Deprecation cascade — many agents may reference a deprecated skill; only notify, do not auto-remove; give 30-day grace period

---

## Testing Requirements

- [ ] Unit test: PA can create skill with sequential_pipeline pattern
- [ ] Unit test: mandate flag prevents tenant from unadopting skill
- [ ] Unit test: adoption stats are aggregate only (no per-tenant data in response)
- [ ] Unit test: promotion approval copies skill to platform scope, does NOT modify original tenant skill
- [ ] Unit test: deprecation creates notification records for all affected tenant admins
- [ ] Integration test: PA publishes skill → appears in TA platform skills catalog
- [ ] E2E test: PA marks skill mandatory → TA skills page shows lock icon, unadopt disabled

---

## Definition of Done

- [ ] Platform Skills Library page renders with all PA management actions
- [ ] Sequential pipeline execution pattern fully editable
- [ ] Mandatory skill flow works end-to-end with impact confirmation
- [ ] Promotion review queue functional
- [ ] Deprecation notifies affected tenants
- [ ] Version history for skills same quality as template version history
- [ ] All acceptance criteria met
