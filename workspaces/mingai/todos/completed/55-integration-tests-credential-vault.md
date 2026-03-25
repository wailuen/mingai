---
id: TODO-55
title: Integration and unit tests — Platform Credential Vault (all 13 test cases)
status: pending
priority: high
phase: Test
dependencies: [TODO-41, TODO-42, TODO-43, TODO-44, TODO-45, TODO-46, TODO-47, TODO-48]
---

## Goal

Implement all 13 test cases from the Platform Credential Vault test plan in `src/backend/tests/integration/` and `src/backend/tests/unit/`. Each test must use real infrastructure (real database, real CredentialManager with Fernet backend) — no mocking of the vault or database layers.

## Context

The test plan covers CRUD correctness, ACL enforcement, concurrency safety, soft-delete semantics, security invariants, and the full runtime path from orchestrator to audit log.

Reference: `workspaces/mingai/02-plans/18-platform-credential-vault-plan.md` — Test Plan table.

## Test Environment Setup

All integration tests in this file need:
- A test database with `v061` migration applied
- `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` set to a test Fernet key (generate one in the test fixture)
- A platform admin user with a valid auth token
- A tenant admin user with a valid auth token (for ACL tests)
- At least one `agent_template` record with `auth_mode = 'platform_credentials'` and `required_credentials = ["TEST_API_KEY"]`

Use `pytest` fixtures. Follow the existing fixture pattern in `src/backend/tests/conftest.py`.

---

## Test Cases

### 1. test_platform_credential_crud (Integration)

Location: `src/backend/tests/integration/test_platform_credential_vault.py`

Tests the full CRUD lifecycle via the API:

```python
def test_platform_credential_crud(client, platform_admin_token, test_template):
    # POST: store a credential
    r = client.post(
        f"/api/v1/platform/templates/{test_template.id}/credentials",
        json={"key": "TEST_API_KEY", "value": "test-secret-value", "description": "Test key"},
        headers={"Authorization": f"Bearer {platform_admin_token}"},
    )
    assert r.status_code == 201
    assert "value" not in r.json()  # Value must never be in response

    # GET: list keys — must show the key, not the value
    r = client.get(...)
    assert r.status_code == 200
    keys = r.json()["credentials"]
    assert any(k["key"] == "TEST_API_KEY" for k in keys)
    assert all("value" not in k for k in keys)

    # PUT: rotate with correct If-Match
    version = next(k["version"] for k in keys if k["key"] == "TEST_API_KEY")
    r = client.put(
        f"/api/v1/platform/templates/{test_template.id}/credentials/TEST_API_KEY",
        json={"value": "new-secret-value"},
        headers={"Authorization": ..., "If-Match": str(version)},
    )
    assert r.status_code == 200
    assert r.json()["version"] == version + 1

    # DELETE: soft-delete (no active agents in this test)
    r = client.delete(...)
    assert r.status_code == 200
    assert r.json()["retention_until"] is not None

    # GET after delete: key excluded from list
    r = client.get(...)
    keys = r.json()["credentials"]
    assert not any(k["key"] == "TEST_API_KEY" for k in keys)
```

---

### 2. test_platform_credential_acl (Integration)

```python
def test_platform_credential_acl(client, tenant_admin_token, test_template):
    # Tenant admin must get 403 on all five endpoints
    for method, path in [
        ("POST", f"/api/v1/platform/templates/{test_template.id}/credentials"),
        ("GET", f"/api/v1/platform/templates/{test_template.id}/credentials"),
        ("PUT", f"/api/v1/platform/templates/{test_template.id}/credentials/KEY"),
        ("DELETE", f"/api/v1/platform/templates/{test_template.id}/credentials/KEY"),
        ("GET", f"/api/v1/platform/templates/{test_template.id}/credentials/health"),
    ]:
        r = getattr(client, method.lower())(
            path, headers={"Authorization": f"Bearer {tenant_admin_token}"}
        )
        assert r.status_code == 403, f"{method} {path} should be 403 for tenant admin"
```

---

### 3. test_platform_credential_rotation_concurrency (Integration)

Simulates two simultaneous PUT requests with the same `If-Match` version. One must succeed (200), one must fail (409). No silent data loss.

```python
def test_platform_credential_rotation_concurrency(client, platform_admin_token, test_template):
    # Store initial credential
    client.post(..., json={"key": "CONCURRENT_KEY", "value": "v1"})

    # Fetch current version
    r = client.get(...)
    version = r.json()["credentials"][0]["version"]  # Should be 1

    # Fire two concurrent PUT requests with the same version
    import concurrent.futures
    def rotate(value):
        return client.put(
            ...,
            json={"value": value},
            headers={"If-Match": str(version)},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(rotate, f"v{i}") for i in [2, 3]]
        results = [f.result() for f in futures]

    status_codes = sorted(r.status_code for r in results)
    assert status_codes == [200, 409], "One rotation must win, one must get 409"
```

---

### 4. test_platform_credential_partial_unique_index (Integration)

```python
def test_platform_credential_partial_unique_index(client, platform_admin_token, test_template):
    # Store a credential
    client.post(..., json={"key": "REUSE_KEY", "value": "v1"})
    # Delete it (soft-delete)
    client.delete(...)
    # Re-provision with the same key name immediately after soft-delete — must succeed
    r = client.post(..., json={"key": "REUSE_KEY", "value": "v2"})
    assert r.status_code == 201, "Re-provisioning after soft-delete must succeed (partial index)"
```

---

### 5. test_credential_scrubber (Unit)

Location: `src/backend/tests/unit/test_credential_scrubber.py`

```python
from app.core.credential_scrubber import CredentialScrubber

def test_scrubber_replaces_credential_in_error():
    resolved = {"API_KEY": "super-secret-value-12345"}
    scrubber = CredentialScrubber(resolved)
    raw = "Request failed: auth=super-secret-value-12345 endpoint=api.example.com"
    scrubbed = scrubber.scrub(raw)
    assert "super-secret-value-12345" not in scrubbed
    assert "[REDACTED]" in scrubbed

def test_scrubber_ignores_short_values():
    resolved = {"SHORT": "abc"}  # len <= 4
    scrubber = CredentialScrubber(resolved)
    text = "contains abc"
    assert scrubber.scrub(text) == text  # Short values not tracked

def test_scrubber_no_false_positives():
    resolved = {"KEY": "real-secret-value-xyz"}
    scrubber = CredentialScrubber(resolved)
    text = "normal log message"
    assert scrubber.scrub(text) == text
```

---

### 6. test_allowed_domains_validation (Integration)

```python
def test_allowed_domains_validation(client, platform_admin_token, test_template, mock_orchestrator):
    # Store credential with restricted allowed_domains
    client.post(..., json={
        "key": "SSRF_TEST_KEY",
        "value": "secret",
        "allowed_domains": ["api.trusted.com"],
    })

    # Attempt tool call to a non-allowed domain — must be blocked
    # (This test may be at integration level with a lightweight mock tool executor
    #  that checks domain validation without making real HTTP calls)
    result = mock_orchestrator.attempt_credential_injection(
        template_id=test_template.id,
        key="SSRF_TEST_KEY",
        endpoint_url="https://attacker.evil.com/steal",
    )
    assert result == "blocked"

    # Verify audit record written for the blocked event
    audit_row = db_session.execute(
        text("SELECT * FROM platform_credential_audit WHERE action='blocked' ORDER BY timestamp DESC LIMIT 1")
    ).mappings().one()
    assert audit_row["action"] == "blocked"
    assert audit_row["metadata"]["endpoint_url"] == "https://attacker.example.com/exfil"
```

---

### 7. test_startup_without_encryption_key (Integration)

```python
def test_startup_without_encryption_key(monkeypatch):
    # Remove both environment variables
    monkeypatch.delenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("VAULT_ADDR", raising=False)

    from app.core.startup_checks import validate_platform_credential_config
    import pytest
    with pytest.raises(RuntimeError, match="Platform credential vault is not configured"):
        validate_platform_credential_config()
```

---

### 8. test_publish_gate_missing_credentials (Integration)

```python
def test_publish_gate_missing_credentials(client, platform_admin_token, test_template):
    # Ensure no credentials are stored for this template
    # Attempt to publish
    r = client.patch(
        f"/api/v1/platform/templates/{test_template.id}",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {platform_admin_token}"},
    )
    assert r.status_code == 422
    assert "Cannot publish: missing platform credentials" in r.json()["detail"]
    assert "TEST_API_KEY" in r.json()["detail"]
```

---

### 9. test_deployment_missing_credentials (Integration)

```python
def test_deployment_missing_credentials(client, platform_admin_token, tenant_admin_token, test_template, test_tenant):
    # Ensure no credentials stored
    # Attempt to deploy the template as a tenant agent
    r = client.post(
        f"/api/v1/tenants/{test_tenant.id}/agents",
        json={"template_id": test_template.id, ...},
        headers={"Authorization": f"Bearer {tenant_admin_token}"},
    )
    assert r.status_code == 422
    assert "Cannot deploy: missing platform credentials" in r.json()["detail"]
```

---

### 10. test_orchestrator_eager_resolution (Integration)

```python
def test_orchestrator_eager_resolution(client, platform_admin_token, test_template, test_agent, chat_session):
    # Do NOT store any credential
    # Send a chat message to the agent
    r = client.post(
        f"/api/v1/chat/{chat_session.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": ...},
    )
    # Must fail with 503 before any tool is called
    assert r.status_code == 503
    assert "temporarily unavailable" in r.json()["detail"].lower()
    # No tool call audit records (credential resolution failed before first tool call)
```

---

### 11. test_audit_record_tenant_context (Integration)

```python
def test_audit_record_tenant_context(db_session, platform_admin_token, test_template, test_tenant):
    # Store credential
    # Deploy and run one query via a test tenant
    # Check platform_credential_audit table
    audit_records = db_session.query(PlatformCredentialAudit).filter(
        PlatformCredentialAudit.action == "resolve",
        PlatformCredentialAudit.template_id == test_template.id,
    ).all()

    assert len(audit_records) > 0
    for record in audit_records:
        assert record.tenant_id == test_tenant.id
        assert record.request_id is not None  # Correlation ID must be set
        assert record.actor_id == "runtime"
```

---

### 12. test_reserved_tenant_id_rejection (Unit)

Location: `src/backend/tests/unit/test_tenant_validation.py`

```python
from app.core.validators import validate_tenant_id
import pytest

@pytest.mark.parametrize("bad_id", ["platform", "PLATFORM", "Platform", "system", "__platform__", "__anything"])
def test_reserved_ids_rejected(bad_id):
    with pytest.raises(ValueError):
        validate_tenant_id(bad_id)

@pytest.mark.parametrize("good_id", ["acme-corp", "tenant123", "my_org", "normal"])
def test_normal_ids_accepted(good_id):
    validate_tenant_id(good_id)  # Must not raise
```

---

### 13. test_credential_not_in_logs (Integration)

```python
def test_credential_not_in_logs(caplog, client, platform_admin_token, test_template):
    import logging
    with caplog.at_level(logging.DEBUG):
        # Store a credential with a distinctive value
        client.post(..., json={"key": "LOG_TEST_KEY", "value": "DISTINCTIVEVALUE-xyz-789"})
        # Rotate it
        client.put(..., json={"value": "NEWVALUE-abc-456"}, headers={"If-Match": "1"})
        # Delete it
        client.delete(...)

    # Neither credential value must appear in any captured log record
    all_log_text = " ".join(record.message for record in caplog.records)
    assert "DISTINCTIVEVALUE-xyz-789" not in all_log_text
    assert "NEWVALUE-abc-456" not in all_log_text
```

---

### 14. test_injection_config_forms (Integration + Unit)

Location: `src/backend/tests/integration/test_platform_credential_vault.py` (integration portion) and `src/backend/tests/unit/test_credential_scrubber.py` (unit portion).

Verifies that all four injection types produce correct outbound auth:

```python
def test_injection_config_bearer(credential_manager, test_template):
    # Store with bearer injection (default)
    credential_manager.set_platform_credential(
        test_template.id, "BEARER_KEY", "mytoken123",
        allowed_domains=["api.example.com"],
        description=None, actor_id="test",
        injection_config={"type": "bearer"},
    )
    resolved = credential_manager.resolve_platform_credentials(
        test_template.id, ["BEARER_KEY"]
    )
    auth_config, query_params = _build_auth_config(resolved)
    # Bearer must produce credentials dict with bearer_token key
    assert auth_config["credentials"]["bearer_token"] == "mytoken123"
    assert "Authorization" not in auth_config.get("header_map", {})


def test_injection_config_custom_header(credential_manager, test_template):
    # PitchBook-style X-Api-Key injection
    credential_manager.set_platform_credential(
        test_template.id, "PITCHBOOK_KEY", "pb-secret-xyz",
        allowed_domains=["api.pitchbook.com"],
        description=None, actor_id="test",
        injection_config={"type": "header", "header_name": "X-Api-Key"},
    )
    resolved = credential_manager.resolve_platform_credentials(
        test_template.id, ["PITCHBOOK_KEY"]
    )
    auth_config, query_params = _build_auth_config(resolved)
    assert auth_config["header_map"]["X-Api-Key"] == "pb-secret-xyz"


def test_injection_config_basic_auth(credential_manager, test_template):
    import base64
    credential_manager.set_platform_credential(
        test_template.id, "BASIC_CRED", "user:password123",
        allowed_domains=["api.example.com"],
        description=None, actor_id="test",
        injection_config={"type": "basic_auth"},
    )
    resolved = credential_manager.resolve_platform_credentials(
        test_template.id, ["BASIC_CRED"]
    )
    auth_config, query_params = _build_auth_config(resolved)
    expected = "Basic " + base64.b64encode(b"user:password123").decode()
    assert auth_config["header_map"]["Authorization"] == expected


def test_injection_config_query_param(credential_manager, test_template):
    credential_manager.set_platform_credential(
        test_template.id, "QUERY_KEY", "qp-value-abc",
        allowed_domains=["api.example.com"],
        description=None, actor_id="test",
        injection_config={"type": "query_param", "param_name": "api_key"},
    )
    resolved = credential_manager.resolve_platform_credentials(
        test_template.id, ["QUERY_KEY"]
    )
    auth_config, query_params = _build_auth_config(resolved)
    assert query_params["api_key"] == "qp-value-abc"


def test_scrubber_covers_all_injection_types():
    """CredentialScrubber must redact values regardless of how they are injected."""
    from app.core.credential_scrubber import CredentialScrubber
    # Scrubber takes plain {key: value} dict — test it handles values from all types
    resolved_values = {
        "BEARER_KEY": "mytoken123",
        "HEADER_KEY": "pb-secret-xyz",
        "BASIC_CRED": "user:password123",
        "QUERY_KEY": "qp-value-abc",
    }
    scrubber = CredentialScrubber(resolved_values)
    raw = "auth=mytoken123 header=pb-secret-xyz basic=user:password123 qp=qp-value-abc"
    scrubbed = scrubber.scrub(raw)
    for val in resolved_values.values():
        assert val not in scrubbed, f"Value '{val}' was not redacted"
    assert scrubbed.count("[REDACTED]") == 4
```

---

## Test File Organisation

```
src/backend/tests/
├── integration/
│   └── test_platform_credential_vault.py   ← tests 1-4, 6-11, 13-14 (integration)
└── unit/
    ├── test_credential_scrubber.py          ← test 5, test 14 (scrubber unit portion)
    └── test_tenant_validation.py            ← test 12
```

## Acceptance Criteria

- [ ] All 14 test cases are implemented (no stubs or `pass` bodies)
- [ ] Tests use real database (real migration applied, real CredentialManager with Fernet)
- [ ] No mocking of the vault layer, database, or HTTP client in Tier 2/3 tests
- [ ] `test_platform_credential_crud` verifies value is never in any response body
- [ ] `test_platform_credential_acl` verifies all 5 endpoints return 403 for tenant admin
- [ ] `test_platform_credential_rotation_concurrency` confirms exactly one 200 and one 409
- [ ] `test_platform_credential_partial_unique_index` confirms re-provisioning after soft-delete succeeds
- [ ] `test_credential_scrubber` is a pure unit test (no DB, no HTTP)
- [ ] `test_startup_without_encryption_key` verifies `RuntimeError` raised when no backend configured
- [ ] `test_publish_gate_missing_credentials` verifies 422 with key names in error detail
- [ ] `test_deployment_missing_credentials` verifies 422 with key names in error detail
- [ ] `test_orchestrator_eager_resolution` verifies 503 before any tool call
- [ ] `test_audit_record_tenant_context` verifies `tenant_id` and `request_id` in audit rows
- [ ] `test_reserved_tenant_id_rejection` tests all four reserved ID patterns
- [ ] `test_credential_not_in_logs` verifies no value appears in structlog output
- [ ] `test_injection_config_forms` (test 14): bearer → `credentials["bearer_token"]`, custom header → `header_map["X-Api-Key"]`, basic_auth → `Authorization: Basic {encoded}`, query_param → `query_params["api_key"]`
- [ ] `test_scrubber_covers_all_injection_types`: scrubber redacts values from all four injection forms
- [ ] `test_allowed_domains_validation` audit assertion: `audit_row["action"] == "blocked"` and `audit_row["metadata"]["endpoint_url"] == "https://attacker.example.com/exfil"`
- [ ] All tests pass with `pytest src/backend/tests/` against the migrated test database
