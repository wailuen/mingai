# Step 3 — Teams (from aihub2 Roles)

**Actor**: Tenant Admin
**Concept mapping**: aihub2 "roles" (with index_permissions) → mingai "tenant_teams" + team memberships
**API**: POST /api/v1/admin/teams (when implemented) | INSERT into `tenant_teams`

---

## Mapping Rationale

In aihub2, **roles** serve dual purpose:

1. Grant access to specific KB indexes (knowledge bases)
2. Grant system permissions (user:manage, index:manage, etc.)

In mingai, **teams** group users for access scoping. System permissions are handled by the `role` column on the `users` table (`user` / `tenant_admin`).

**Mapping rule**:

- aihub2 custom roles (business-purpose) → mingai `tenant_teams`
- aihub2 system roles (`admin`, `analytics_viewer`, `user_admin`, etc.) → mingai `role` field on user (tenant_admin / user)
- aihub2 `index_permissions` on roles → mingai team + integration scoping (Phase 5 cross-reference)

---

## 3.1 System Role → mingai User Role Mapping

| aihub2 system role | aihub2 users assigned                                          | mingai action                                        |
| ------------------ | -------------------------------------------------------------- | ---------------------------------------------------- |
| `admin`            | cloudadmwailuen@imcshipping.com.sg, admin@localtest.me         | Set role=`tenant_admin`                              |
| `analytics_viewer` | viewer_test@localtest.me, CheongWaiLuen@imcindustrialgroup.com | Set role=`user` (analytics not a role in mingai yet) |
| All others         | Various test users                                             | Excluded (test accounts)                             |

---

## 3.2 Business Teams to Create

Create each team via `INSERT INTO tenant_teams` or Tenant Admin UI:

```sql
-- Template
INSERT INTO tenant_teams (tenant_id, name, description, source)
VALUES ('<tenant_id>', '<name>', '<description>', 'manual');
```

### Team Definitions

| #   | Team Name             | Description                               | aihub2 Role ID  |
| --- | --------------------- | ----------------------------------------- | --------------- |
| 1   | TPC Singapore         | All Singapore-based TPC users             | `role-795ea5b2` |
| 2   | TPC Indonesia         | All Indonesia-based TPC users             | `role-b7c9deec` |
| 3   | TPC Thailand          | All Thailand-based TPC users              | `role-73272770` |
| 4   | TPC China             | All TPC China staff                       | `role-332e9398` |
| 5   | TPC Treasury          | Treasury access only                      | `role-e8006f55` |
| 6   | TPC GIC               | Group Investment Committee                | `role-2a133111` |
| 7   | TPC Investment        | Investment tools (PitchBook, CapIQ)       | `role-a37c95f6` |
| 8   | TPC Corp Sec          | Corporate Secretariat (Teamworks)         | `role-a0dfb2d2` |
| 9   | UTSE Specific         | Unithai UTSE ISO access                   | `role-0ee8d30d` |
| 10  | IMC Shipping          | IMC Shipping Dry Bulk                     | `role-5faea3c0` |
| 11  | Aurora Tankers        | AT Liquid Bulk users                      | `role-24881099` |
| 12  | MEP Coaching Program  | Mindful Emotion Program participants      | `role-1bc1a54e` |
| 13  | Demo                  | Demo access (multi-KB + research tools)   | `role-affc55df` |
| 14  | Oracle Staging        | Oracle Fusion testing                     | `role-cec3ec55` |
| 15  | Knowledgebase Manager | Can add/delete SharePoint folders from KB | `role-38e2a2e0` |

---

## 3.3 Team Memberships

Based on `user_roles` assignments in aihub2 CosmosDB:

| User Email                             | Team(s)                                                   |
| -------------------------------------- | --------------------------------------------------------- |
| `ss@integrum.global` (Fuji Foo)        | TPC Singapore, MEP Coaching Program — **EXCLUDED** (test) |
| `cloudadmwailuen@imcshipping.com.sg`   | IMC Shipping, TPC China — set as tenant_admin             |
| `wailuen.cheong@gmail.com`             | TPC Singapore, TPC Investment — **EXCLUDED** (test)       |
| `ma.jiajia@imcindustrialgroup.com`     | Demo, TPC GIC                                             |
| `jack@integrum.global`                 | Demo — **EXCLUDED** (test)                                |
| `axeltan@octavecapital.co`             | Demo — **EXCLUDED** (test)                                |
| `axeltan@heritas.com.sg`               | Demo                                                      |
| `achmad.nadjib@imcindustrialgroup.com` | Oracle Staging                                            |
| `varinthorn.s@tsaopaochee.com`         | TPC Investment                                            |
| `viewer_test@localtest.me`             | (analytics_viewer) — **EXCLUDED** (test)                  |

> Note: Most aihub2 users were assigned roles via Azure AD group membership (group_roles), not direct user_roles. Only 23 direct `user_roles` assignments exist. The majority of team membership must be reconstructed manually by the tenant admin based on department/entity.

---

## 3.4 Recommended Team Assignment by Department

Use aihub2 user `department` field as a guide:

| Department                   | Suggested Team                        |
| ---------------------------- | ------------------------------------- |
| IT (IMC group)               | No specific team (general access)     |
| Finance Share Service Center | TPC Singapore or relevant geo         |
| Group Treasury               | TPC Treasury                          |
| People & Organisation        | TPC Singapore / geo                   |
| Development Office           | (Octave Institute — no specific team) |
| Controllership               | TPC China or geo                      |
| Corporate Communication      | TPC Singapore                         |
| Group Strategic Development  | TPC GIC                               |
| Operations (Aurora)          | Aurora Tankers                        |
| Operations (UTSE)            | UTSE Specific                         |
| Commercial/Sales (Aurora)    | Aurora Tankers                        |
| Management (UTSE)            | UTSE Specific                         |
| Freight Forwarding (UTSE)    | UTSE Specific                         |

---

## Verification Checklist

- [ ] 15 teams created in `tenant_teams`
- [ ] cloudadmwailuen is NOT in any team (they are tenant_admin)
- [ ] Known explicit memberships (from user_roles) assigned
- [ ] Tenant admin reviews remaining users and assigns teams by department
