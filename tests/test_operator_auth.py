from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import main
from dashboard.auth import can
from services.operator_auth import (
    ROLE_PERMISSIONS,
    OperatorAuthError,
    OperatorPrincipal,
    principal_from_record,
    verify_oidc_token,
)
from services.recommendation_history import decision_timeline


RECOMMENDATION_ID = "22222222-2222-2222-2222-222222222222"
OPERATOR_ID = "55555555-5555-5555-5555-555555555555"
PORTFOLIO_ID = "11111111-1111-1111-1111-111111111111"
DISPATCH_ID = "44444444-4444-4444-4444-444444444444"
AUTH_HEADERS = {"Authorization": "Bearer verified-oidc-token"}


def operator_record(role="viewer", status="active"):
    return {
        "id": OPERATOR_ID, "auth_subject": "oidc-subject-1",
        "email": "jane@pubba.test", "display_name": "Jane Operator",
        "role": role, "status": status,
    }


def recommendation_record(**updates):
    record = {
        "id": RECOMMENDATION_ID, "portfolio_id": PORTFOLIO_ID,
        "asset_id": "BAT-1", "generated_at": "2026-07-18T03:00:00Z",
        "captured_at": "2026-07-18T03:01:00Z", "market_price": 100,
        "opportunity_score": 88, "recommendation": "Strong discharge opportunity",
        "recommendation_direction": "discharge", "estimated_charging_cost": 1000,
        "estimated_discharge_revenue": 4000, "estimated_gross_profit": 3000,
        "estimated_margin": 75, "simulation_id": None, "dispatch_id": None,
    }
    record.update(updates)
    return record


def configure_auth(monkeypatch, *, role="viewer", status="active"):
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "true")
    monkeypatch.setattr(
        main, "verify_oidc_token",
        lambda token: SimpleNamespace(subject="oidc-subject-1", email="spoof-proof@pubba.test"),
    )
    monkeypatch.setattr(
        main, "get_operator_by_subject", lambda subject: operator_record(role, status)
    )


def configure_workflow_storage(monkeypatch, *, role="approver", status="active"):
    configure_auth(monkeypatch, role=role, status=status)
    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")
    persisted = recommendation_record()
    monkeypatch.setattr(main, "get_recommendation_history", lambda value: dict(persisted))
    monkeypatch.setattr(main, "get_simulation_result", lambda value: None)
    monkeypatch.setattr(main, "get_dispatch_event_record", lambda value: None)
    monkeypatch.setattr(main, "get_recommendation_approval", lambda value: None)
    monkeypatch.setattr(main, "list_operator_audit_events", lambda **kwargs: [])
    monkeypatch.setattr(main, "get_operator", lambda value: operator_record(role, status))
    def update(value, fields):
        persisted.update(fields)
        return dict(persisted)
    monkeypatch.setattr(main, "update_recommendation_links", update)
    audits = []
    monkeypatch.setattr(
        main, "create_operator_audit_event",
        lambda fields: audits.append(dict(fields)) or {"id": "audit-1", **fields},
    )
    return persisted, audits


def test_unauthenticated_operator_access_is_401(monkeypatch):
    configure_auth(monkeypatch)
    response = TestClient(main.app).get("/operators/me")
    assert response.status_code == 401


def test_valid_active_operator_resolves_from_verified_subject(monkeypatch):
    configure_auth(monkeypatch, role="operator")

    response = TestClient(main.app).get("/operators/me", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "id": OPERATOR_ID,
        "email": "jane@pubba.test",
        "display_name": "Jane Operator",
        "role": "operator",
        "status": "active",
    }


def test_unknown_operator_is_not_provisioned(monkeypatch):
    configure_auth(monkeypatch)
    monkeypatch.setattr(main, "get_operator_by_subject", lambda subject: None)

    response = TestClient(main.app).get("/operators/me", headers=AUTH_HEADERS)

    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_not_provisioned"


def test_invalid_operator_credential_is_rejected(monkeypatch):
    monkeypatch.setattr(
        main,
        "verify_oidc_token",
        lambda token: (_ for _ in ()).throw(OperatorAuthError("invalid credential")),
    )

    response = TestClient(main.app).get("/operators/me", headers=AUTH_HEADERS)

    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_operator_credential"


def test_viewer_can_read_history_but_cannot_write(monkeypatch):
    configure_auth(monkeypatch, role="viewer")
    monkeypatch.setattr(main, "list_recommendation_history", lambda **kwargs: [])
    client = TestClient(main.app)
    assert client.get("/recommendations/history", headers=AUTH_HEADERS).status_code == 200
    denied = client.post("/recommendations/BAT-1/capture", headers=AUTH_HEADERS)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "operator_forbidden"


def test_recommendation_write_flags_fail_closed(monkeypatch):
    configure_auth(monkeypatch, role="operator")
    client = TestClient(main.app)

    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "false")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")
    disabled = client.post("/recommendations/BAT-1/capture", headers=AUTH_HEADERS)
    assert disabled.status_code == 403
    assert disabled.json()["error_code"] == "recommendation_writes_disabled"

    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "false")
    no_storage = client.post("/recommendations/BAT-1/capture", headers=AUTH_HEADERS)
    assert no_storage.status_code == 503
    assert no_storage.json()["error_code"] == "operator_audit_storage_disabled"


def test_admin_cannot_bypass_disabled_recommendation_writes(monkeypatch):
    configure_auth(monkeypatch, role="admin")
    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "false")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")

    response = TestClient(main.app).post(
        "/recommendations/BAT-1/capture", headers=AUTH_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "recommendation_writes_disabled"


def test_operator_cannot_link_dispatch_even_with_spoofed_role_header(monkeypatch):
    configure_workflow_storage(monkeypatch, role="operator")
    response = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/link-dispatch",
        json={"record_id": DISPATCH_ID},
        headers={**AUTH_HEADERS, "X-Operator-Role": "admin", "X-Operator-Email": "admin@pubba.test"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_forbidden"


def test_inactive_operator_is_rejected(monkeypatch):
    configure_auth(monkeypatch, role="admin", status="inactive")
    response = TestClient(main.app).get("/operators/me", headers=AUTH_HEADERS)
    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_inactive"


def test_invalid_database_role_fails_closed(monkeypatch):
    configure_auth(monkeypatch, role="superuser")
    response = TestClient(main.app).get("/operators/me", headers=AUTH_HEADERS)
    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_access_denied"


def test_approver_records_explicit_approval_and_audit(monkeypatch):
    _, audits = configure_workflow_storage(monkeypatch, role="approver")
    captured = {}
    monkeypatch.setattr(
        main, "create_recommendation_approval",
        lambda fields: captured.update(fields) or {"id": "approval-1", "approved_at": "2026-07-18T03:15:00Z", **fields},
    )
    response = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/approval",
        json={"approval_status": "approved", "note": "Reviewed market and simulation"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    assert captured["approved_by_operator_id"] == OPERATOR_ID
    assert captured["approval_status"] == "approved"
    assert audits[0]["action"] == "recommendation_approved"
    assert "authorization" not in str(audits).lower()


def test_operator_explicitly_reviews_linked_simulation(monkeypatch):
    persisted, audits = configure_workflow_storage(monkeypatch, role="operator")
    persisted["simulation_id"] = "33333333-3333-3333-3333-333333333333"
    monkeypatch.setattr(main, "get_simulation_result", lambda value: {
        "id": value, "portfolio_id": PORTFOLIO_ID, "asset_id": "BAT-1",
    })
    response = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/review-simulation",
        json={"note": "Assumptions reviewed"}, headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert audits[0]["action"] == "simulation_reviewed"


def test_admin_operator_management_is_backend_enforced_and_audited(monkeypatch):
    configure_auth(monkeypatch, role="admin")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")
    monkeypatch.setattr(main, "list_operators", lambda **kwargs: [operator_record("admin")])
    monkeypatch.setattr(main, "create_operator_audit_event", lambda fields: {"id": "audit-1", **fields})
    monkeypatch.setattr(
        main, "create_operator",
        lambda fields: {"id": "66666666-6666-6666-6666-666666666666", **fields},
    )
    monkeypatch.setattr(
        main, "update_operator",
        lambda operator_id, fields: {"id": operator_id, **operator_record("viewer", "inactive"), **fields},
    )
    client = TestClient(main.app)
    assert client.get("/operators", headers=AUTH_HEADERS).status_code == 200
    created = client.post("/operators", headers=AUTH_HEADERS, json={
        "auth_subject": "oidc-subject-2", "email": "new@pubba.test",
        "display_name": "New Operator", "role": "operator", "status": "active",
    })
    assert created.status_code == 201
    assert created.json()["role"] == "operator"
    updated = client.patch(
        f"/operators/{OPERATOR_ID}", headers=AUTH_HEADERS,
        json={"role": "viewer", "status": "inactive"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "inactive"


def test_non_admin_operator_management_is_rejected(monkeypatch):
    configure_auth(monkeypatch, role="approver")
    assert TestClient(main.app).get("/operators", headers=AUTH_HEADERS).status_code == 403


def test_real_operator_attribution_appears_in_decision_timeline():
    event = {
        "action": "recommendation_captured", "occurred_at": "2026-07-18T03:02:00Z",
        "operator": {"display_name": "Jane Operator"},
    }
    timeline = decision_timeline(recommendation_record(), audit_events=[event])
    captured = next(item for item in timeline if item["event"] == "recommendation_captured")
    assert captured["attribution"] == "Jane Operator"


def test_role_aware_dashboard_permissions_are_conservative():
    assert can({"role": "viewer", "status": "active"}, "operator") is False
    assert can({"role": "operator", "status": "active"}, "operator") is True
    assert can({"role": "approver", "status": "active"}, "approver", "admin") is True
    assert can({"role": "admin", "status": "inactive"}, "admin") is False


def test_backend_role_permission_matrix_is_exact():
    assert ROLE_PERMISSIONS == {
        "viewer": frozenset({"recommendations:read"}),
        "operator": frozenset({
            "recommendations:read",
            "recommendations:capture",
            "recommendations:acknowledge",
            "recommendations:link_simulation",
        }),
        "approver": frozenset({
            "recommendations:read",
            "recommendations:capture",
            "recommendations:acknowledge",
            "recommendations:link_simulation",
            "recommendations:approve",
            "recommendations:link_dispatch",
        }),
        "admin": frozenset({
            "recommendations:read",
            "recommendations:capture",
            "recommendations:acknowledge",
            "recommendations:link_simulation",
            "recommendations:approve",
            "recommendations:link_dispatch",
            "assets:manage",
            "operators:manage",
        }),
    }


@pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/assets", {"asset_id": "BAT-RBAC", "asset_name": "RBAC Battery"}),
        ("patch", "/assets/BAT-RBAC", {"status": "inactive"}),
    ],
)
def test_non_admin_asset_management_is_backend_denied(
    monkeypatch, role, method, path, payload,
):
    configure_auth(monkeypatch, role=role)
    response = getattr(TestClient(main.app), method)(
        path, headers=AUTH_HEADERS, json=payload,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_forbidden"


def test_asset_management_requires_authentication():
    response = TestClient(main.app).patch(
        "/assets/BAT-RBAC", json={"status": "inactive"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_required"


def test_admin_asset_management_is_backend_authorized(monkeypatch):
    configure_auth(monkeypatch, role="admin")
    monkeypatch.setattr(
        main, "create_asset", lambda fields: {"id": "asset-uuid", **fields},
    )
    monkeypatch.setattr(
        main, "update_asset", lambda asset_id, fields: {"asset_id": asset_id, **fields},
    )
    client = TestClient(main.app)

    created = client.post(
        "/assets", headers=AUTH_HEADERS,
        json={"asset_id": "BAT-RBAC", "asset_name": "RBAC Battery"},
    )
    updated = client.patch(
        "/assets/BAT-RBAC", headers=AUTH_HEADERS, json={"status": "inactive"},
    )

    assert created.status_code == 201
    assert updated.status_code == 200


def test_principal_public_shape_does_not_expose_internal_identity():
    principal = principal_from_record(operator_record("admin"))
    assert isinstance(principal, OperatorPrincipal)
    assert "operator_id" not in principal.public_dict()
    assert "auth_subject" not in principal.public_dict()


def test_operator_identity_migration_is_additive_and_constrained():
    sql = Path("supabase/migrations/202607180002_operator_identity_rbac.sql").read_text()
    for table in ("operators", "recommendation_approvals", "operator_audit_events"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "foreign key (recommendation_id) references public.recommendation_history(id)" in sql
    assert "foreign key (approved_by_operator_id) references public.operators(id)" in sql
    assert "prevent_operator_audit_mutation" in sql
    assert "drop table" not in sql.lower()
    assert "alter table public.recommendation_history" not in sql.lower()


def test_oidc_verification_fails_closed_without_provider_configuration(monkeypatch):
    monkeypatch.delenv("OPERATOR_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OPERATOR_OIDC_AUDIENCE", raising=False)
    try:
        verify_oidc_token("browser-supplied-value")
    except OperatorAuthError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("Unconfigured OIDC verification must fail closed")
