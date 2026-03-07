# Step 2 — User Provisioning

**Actor**: Platform Admin (first admin invite) → Tenant Admin (bulk invite)
**API**: POST /api/v1/admin/users/invite | POST /api/v1/admin/users/bulk-invite

---

## 2.1 Invite the First Tenant Admin

The Platform Admin must invite at least one tenant admin before the tenant admin can self-serve.
This user will log in and perform steps 3–7.

**API**: `POST /api/v1/admin/users/invite` (authenticated as platform admin, scoped to tenant)

```json
{
  "email": "cloudadmwailuen@imcshipping.com.sg",
  "role": "tenant_admin"
}
```

Secondary admin (backup):

```json
{
  "email": "CheongWaiLuen@imcindustrialgroup.com",
  "role": "tenant_admin"
}
```

---

## 2.2 Bulk-Invite All Real Users

**API**: `POST /api/v1/admin/users/bulk-invite` (max 50 per call — split into 2 batches)

Filter applied: **exclude** all test/local accounts (`localtest.me`, `integrum.global`, `gmail.com`, `octavecapital.co`).

### Batch 1 (30 users)

```json
{
  "users": [
    { "email": "marypan@octaveliving.com", "role": "user" },
    { "email": "karengoh@tsaopaochee.com", "role": "user" },
    { "email": "danlin.loh@tsaopaochee.com", "role": "user" },
    { "email": "joanneteh@octaveinstitute.com", "role": "user" },
    { "email": "keane.kee@tsaopaochee.com", "role": "user" },
    { "email": "lilianyang@octaveliving.com", "role": "user" },
    { "email": "ma.jiajia@imcindustrialgroup.com", "role": "user" },
    { "email": "vanessachng@imcindustrialgroup.com", "role": "user" },
    { "email": "eeling.teo@octaveinstitute.com", "role": "user" },
    { "email": "dafd5b60-axeltan@heritas.com.sg", "role": "user" },
    { "email": "axeltan@heritas.com.sg", "role": "user" },
    { "email": "daniel.aryanto@ptplb.com", "role": "user" },
    { "email": "lensy.suteja@imcpelitalog.com", "role": "user" },
    { "email": "bruno.lorenzon@tsaopaochee.com", "role": "user" },
    { "email": "alison.gao@imcindustrialgroup.com", "role": "user" },
    { "email": "achmad.nadjib@imcindustrialgroup.com", "role": "user" },
    { "email": "sam.chau@tsaopaochee.com", "role": "user" },
    { "email": "sheryl.sng@imcindustrialgroup.com", "role": "user" },
    { "email": "monicazhu@octaveliving.com", "role": "user" },
    { "email": "jessiegong@octaveliving.com", "role": "user" },
    { "email": "careen.tan@octaveinstitute.com", "role": "user" },
    { "email": "photchaman.t@tsaopaochee.com", "role": "user" },
    { "email": "pornpitoon.t@tsaopaochee.com", "role": "user" },
    { "email": "phiraphol.n@tsaopaochee.com", "role": "user" },
    { "email": "cedriclua@imcindustrialgroup.com", "role": "user" },
    { "email": "varinthorn.s@tsaopaochee.com", "role": "user" },
    { "email": "gavin.lum@tsaopaochee.com", "role": "user" },
    { "email": "tianchi.pan@tsaopaochee.com", "role": "user" },
    { "email": "hareesh.nair@tsaopaochee.com", "role": "user" },
    { "email": "vivian.ho@octaveinstitute.com", "role": "user" }
  ]
}
```

### Batch 2 (30 users)

```json
{
  "users": [
    { "email": "harjeev.kochar@auroratankers.com", "role": "user" },
    { "email": "jutamas.s@tsaopaochee.com", "role": "user" },
    { "email": "cheongjunna@tsaopaochee.com", "role": "user" },
    { "email": "janicekoo@tsaopaochee.com", "role": "user" },
    { "email": "weijin.toh@tsaopaochee.com", "role": "user" },
    { "email": "jamesong@tsaopaochee.com", "role": "user" },
    { "email": "charinee.h@tsaopaochee.com", "role": "user" },
    { "email": "susidda.p@octaveliving.com", "role": "user" },
    { "email": "gleeson.john@msiships.com", "role": "user" },
    { "email": "marcjudit@imcindustrialgroup.com", "role": "user" },
    { "email": "ivan.hiew@octaveinstitute.com", "role": "user" },
    { "email": "xavior.looi@imcindustrialgroup.com", "role": "user" },
    { "email": "paulinelim@tsaopaochee.com", "role": "user" },
    { "email": "sharlynnong@imcindustrialgroup.com", "role": "user" },
    { "email": "oktavida.ronauli@imcpelitalog.com", "role": "user" },
    { "email": "subhash.pithisaria@auroratankers.com", "role": "user" },
    { "email": "naruphat.k@unithai.com", "role": "user" },
    { "email": "suttirux.k@unithai.com", "role": "user" },
    { "email": "robin.pho@tsaopaochee.com", "role": "user" },
    { "email": "jurgenneo@imcindustrialgroup.com", "role": "user" },
    { "email": "hirotatsu.tanji@tsaopaochee.com", "role": "user" },
    { "email": "damrong.y@unithai.com", "role": "user" },
    { "email": "pradeep.s@unithai.com", "role": "user" },
    { "email": "panupong.f@unithai.com", "role": "user" },
    { "email": "franksha@octaveliving.com", "role": "user" },
    { "email": "pamleonardo.chandra@imcshipping.com.sg", "role": "user" },
    { "email": "leonardo.chandra@imcpelitalog.com", "role": "user" },
    { "email": "chongleemooi@imcindustrialgroup.com", "role": "user" },
    { "email": "chirapong.k@unithai.com", "role": "user" },
    { "email": "juthanuch.b@unithai.com", "role": "user" }
  ]
}
```

### Batch 3 (remaining)

```json
{
  "users": [
    { "email": "howardhew@imc-shipmanagement.com", "role": "user" },
    { "email": "nattakarn.t@unithai.com", "role": "user" },
    { "email": "ojas.iyer@tsaopaochee.com", "role": "user" },
    { "email": "tanapohn.a@tsaopaochee.com", "role": "user" },
    { "email": "peggy.tan@octaveinstitute.com", "role": "user" },
    { "email": "hooiweon.tey@auroratankers.com", "role": "user" },
    { "email": "hitoshi.kamikubo@tsaopaochee.com", "role": "user" },
    { "email": "dante.t@unithai.com", "role": "user" },
    { "email": "kanchanawadee.p@unithai.com", "role": "user" },
    { "email": "zeyouxia@octaveliving.com", "role": "user" },
    { "email": "jaruay.y@unithai.com", "role": "user" },
    { "email": "9e3f449f-robin.pho@tsaopaochee.com", "role": "user" }
  ]
}
```

---

## 2.3 Users Excluded (Test / Local Accounts)

These aihub2 accounts are test/dev-only and should NOT be migrated:

| Email                           | Reason                |
| ------------------------------- | --------------------- |
| `admin@localtest.me`            | System local admin    |
| `ss@integrum.global`            | Integrum test         |
| `jack@integrum.global`          | Integrum test         |
| `wailuen.cheong@gmail.com`      | Personal test account |
| `axeltan@octavecapital.co`      | Local test variant    |
| `viewer_test@localtest.me`      | Analytics viewer test |
| `test.integration@localtest.me` | Integration test      |
| `test.user@localtest.me`        | User admin test       |
| `test.glossary@localtest.me`    | Glossary test         |
| `test.feedback@localtest.me`    | Feedback test         |
| `test.sync@localtest.me`        | Sync test             |
| `test.index@localtest.me`       | Index test            |

---

## 2.4 User Authentication

aihub2 uses **dual mode** (Azure AD SSO + local email/password):

- All real users (above) authenticate via **Azure AD SSO** with Entra tenant `2311a55c-d508-4e3a-aeb8-47a08b156aa5`
- In mingai Phase 1, users are invited by email; SSO login completes their registration
- No passwords are migrated — users SSO in for first login

---

## Verification Checklist

- [ ] `cloudadmwailuen@imcshipping.com.sg` created as `tenant_admin`
- [ ] `CheongWaiLuen@imcindustrialgroup.com` created as `tenant_admin`
- [ ] All 3 bulk-invite batches sent with no failures
- [ ] User count in tenant detail shows ~62 users
