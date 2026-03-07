# Step 1 — Tenant Creation, LLM Profile & Quotas

**Actor**: Platform Admin
**UI location**: Platform Admin > Tenants > New Tenant (or via API)
**API endpoints**: POST /api/v1/admin/tenants (if implemented), PATCH /api/v1/admin/tenants/{id}/quota

---

## 1.1 Create the Tenant Record

Use the Platform Admin "New Tenant" wizard or INSERT directly into the `tenants` table.

| Field                   | Value                                        |
| ----------------------- | -------------------------------------------- |
| `name`                  | `IMC / Tsao Pao Chee Group`                  |
| `slug`                  | `imc-tpc-group`                              |
| `plan`                  | `enterprise`                                 |
| `status`                | `active`                                     |
| `primary_contact_email` | `cloudadmwailuen@imcshipping.com.sg`         |
| `llm_profile_id`        | _(leave null for now — link after step 1.2)_ |

**SQL (if doing directly)**:

```sql
INSERT INTO tenants (name, slug, plan, status, primary_contact_email)
VALUES (
  'IMC / Tsao Pao Chee Group',
  'imc-tpc-group',
  'enterprise',
  'active',
  'cloudadmwailuen@imcshipping.com.sg'
)
RETURNING id;
```

> Save the returned `tenant_id` UUID — needed for every subsequent step.

---

## 1.2 Create LLM Profile (Platform Pre-configured)

Use the **platform pre-configured Azure OpenAI** (eastus2). Do NOT use aihub2's own Azure OpenAI endpoint.

> **If a platform LLM profile for eastus2 already exists** (from a prior tenant setup): skip the
> POST below and simply run the UPDATE to link the existing profile to this tenant.
> Only create a new profile if one does not yet exist.

**API**: `POST /api/v1/admin/llm-profiles`

```json
{
  "tenant_id": "<tenant_id from 1.1>",
  "name": "IMC Platform LLM",
  "provider": "azure_openai",
  "primary_model": "agentic-worker",
  "intent_model": "agentic-router",
  "embedding_model": "text-embedding-3-small",
  "endpoint_url": "https://eastus2.api.cognitive.microsoft.com/"
}
```

> Record the returned `profile_id`. Then link it back to the tenant:

```sql
UPDATE tenants
SET llm_profile_id = '<profile_id>'
WHERE id = '<tenant_id>';
```

**Model reference** (from `MEMORY.md`):
| Slot | Deployment | Model | Purpose |
|---|---|---|---|
| primary_model | `agentic-worker` | gpt-5.2 v2025-12-11 | Main chat |
| intent_model | `agentic-router` | gpt-5-mini v2025-08-07 | Routing / intent |
| embedding_model | `text-embedding-3-small` | text-embedding-3-small | Vector search |

---

## 1.3 Set Tenant Quotas

**API**: `PATCH /api/v1/admin/tenants/{tenant_id}/quota`

```json
{
  "rate_limit_rpm": 200,
  "monthly_token_budget": 50000000,
  "storage_gb": 100.0,
  "users_max": 200
}
```

Rationale from aihub2 `.env`:

- `RATE_LIMIT_PER_USER_PER_MINUTE=100` — enterprise, but platform default 60 is low; set 200 for headroom
- aihub2 has ~60 real users + growth expected; 200 user max is safe
- 33 KB indexes × ~2,000 docs avg = ~66K docs; 100 GB storage is appropriate

---

## 1.4 Transition Tenant to Active

If tenant was created in `draft` status, activate it:

**API**: `PATCH /api/v1/admin/tenants/{tenant_id}/status`

```json
{
  "status": "active",
  "reason": "IMC Group tenant provisioning complete"
}
```

---

## Verification Checklist

- [ ] Tenant row exists in `tenants` table with status=`active`
- [ ] LLM profile exists in `llm_profiles` with all three model slots filled
- [ ] `tenants.llm_profile_id` points to the profile
- [ ] Quota row exists in `tenant_configs` with `config_type='quota'`
- [ ] Platform admin dashboard shows the new tenant in tenant list
