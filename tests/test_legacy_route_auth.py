from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from services.operator_auth import OperatorAuthError
from tests.test_main import make_lmp_frame, simulation_payload
from tests.test_operator_auth import AUTH_HEADERS, configure_auth, operator_record


LEGACY_PLATFORM_ROUTES = [
    ("get", "/assets", None),
    ("get", "/assets/BAT-001", None),
    ("get", "/telemetry/assets/BAT-001/latest", None),
    ("get", "/telemetry/assets/BAT-001/history", None),
    ("get", "/telemetry/portfolio/latest", None),
    ("get", "/telemetry/sources/health", None),
    ("get", "/dispatch-events/export.csv", None),
    ("get", "/reports/daily", None),
    ("get", "/reports/weekly", None),
    ("get", "/reports/monthly", None),
    ("get", "/reports/quarterly", None),
    ("get", "/reports/yearly", None),
    ("get", "/lmp", None),
    ("get", "/arbitrage", None),
    ("get", "/simulate?power_mw=10", None),
    ("post", "/simulate", simulation_payload()),
]


@pytest.mark.parametrize(("method", "path", "payload"), LEGACY_PLATFORM_ROUTES)
def test_enforce_mode_requires_authentication_for_every_legacy_platform_route(
    monkeypatch, method, path, payload,
):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "enforce")
    response = TestClient(main.app).request(method.upper(), path, json=payload)
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_required"


def test_off_mode_preserves_anonymous_legacy_read(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "off")
    monkeypatch.setattr(
        main, "verify_oidc_token",
        lambda token: (_ for _ in ()).throw(AssertionError("off mode evaluated identity")),
    )
    monkeypatch.setattr(main, "list_assets", lambda **kwargs: [])
    assert TestClient(main.app).get("/assets").status_code == 200


def test_shadow_mode_logs_sanitized_would_deny_and_allows_read(
    monkeypatch, caplog,
):
    secret_token = "secret.legacy.route.token"
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "shadow")
    monkeypatch.setattr(
        main, "verify_oidc_token",
        lambda token: (_ for _ in ()).throw(OperatorAuthError("invalid credential")),
    )
    monkeypatch.setattr(main, "list_assets", lambda **kwargs: [])

    response = TestClient(main.app).get(
        "/assets", headers={"Authorization": f"Bearer {secret_token}"},
    )

    assert response.status_code == 200
    assert "would_deny" in [getattr(record, "outcome", "") for record in caplog.records]
    assert secret_token not in caplog.text


@pytest.mark.parametrize("role", ["viewer", "operator", "approver", "admin"])
def test_all_active_roles_can_execute_persisted_simulation_in_enforce_mode(
    monkeypatch, role,
):
    configure_auth(monkeypatch, role=role)
    monkeypatch.setattr(
        main, "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    monkeypatch.setattr(main, "persist_simulation", lambda *args: {
        "status": "saved", "simulation_id": "sim-1", "dispatch_id": None,
        "error_code": None, "message": "Simulation saved",
    })
    response = TestClient(main.app).post(
        "/simulate", headers=AUTH_HEADERS, json=simulation_payload(),
    )
    assert response.status_code == 200
    assert response.json()["persistence"]["status"] == "saved"


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("unknown", "operator_not_provisioned"),
        ("inactive", "operator_inactive"),
        ("invalid_role", "operator_access_denied"),
        ("invalid_credential", "invalid_operator_credential"),
    ],
)
def test_enforce_mode_legacy_routes_fail_closed_for_invalid_identity_states(
    monkeypatch, state, expected_code,
):
    configure_auth(monkeypatch)
    if state == "unknown":
        monkeypatch.setattr(main, "get_operator_by_subject", lambda subject: None)
    elif state == "inactive":
        monkeypatch.setattr(
            main, "get_operator_by_subject",
            lambda subject: operator_record(status="inactive"),
        )
    elif state == "invalid_role":
        monkeypatch.setattr(
            main, "get_operator_by_subject",
            lambda subject: operator_record(role="superuser"),
        )
    else:
        monkeypatch.setattr(
            main, "verify_oidc_token",
            lambda token: (_ for _ in ()).throw(OperatorAuthError("invalid credential")),
        )

    response = TestClient(main.app).get("/assets", headers=AUTH_HEADERS)
    assert response.status_code in {401, 403}
    assert response.json()["error_code"] == expected_code


def test_spoofed_identity_headers_cannot_provision_unknown_operator(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "enforce")
    monkeypatch.setattr(
        main, "verify_oidc_token",
        lambda token: SimpleNamespace(subject="unknown-subject", email="real@pubba.test"),
    )
    monkeypatch.setattr(main, "get_operator_by_subject", lambda subject: None)
    response = TestClient(main.app).get("/assets", headers={
        **AUTH_HEADERS,
        "X-Operator-ID": "55555555-5555-5555-5555-555555555555",
        "X-Operator-Role": "admin",
        "X-Operator-Email": "admin@pubba.test",
        "X-Operator-Display-Name": "Fake Admin",
    })
    assert response.status_code == 403
    assert response.json()["error_code"] == "operator_not_provisioned"


def test_health_and_root_remain_public_in_enforce_mode(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "enforce")
    monkeypatch.setattr(main, "check_supabase_connectivity", lambda: "connected")
    client = TestClient(main.app)
    assert client.get("/").status_code == 200
    health = client.get("/health")
    assert health.status_code == 200
    assert set(health.json()) == {
        "status", "service_name", "api_version", "current_utc_timestamp",
        "supabase_connectivity_status",
    }
