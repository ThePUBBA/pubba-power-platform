from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

import main
import services.operator_auth as operator_auth
from dashboard.api_client import Only1ApiClient
from services.operator_auth import OperatorAuthError, operator_auth_mode, verify_oidc_token
from supabase import SupabaseError
from tests.test_operator_auth import (
    AUTH_HEADERS, OPERATOR_ID, PORTFOLIO_ID, RECOMMENDATION_ID,
    configure_auth, configure_workflow_storage,
)


OTHER_PORTFOLIO = "99999999-9999-9999-9999-999999999999"


def test_valid_oidc_identity_uses_verified_subject(monkeypatch):
    monkeypatch.setenv("OPERATOR_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("OPERATOR_OIDC_AUDIENCE", "pubba-api")
    monkeypatch.setattr(
        operator_auth, "_jwks_client",
        lambda issuer: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key="key")),
    )
    monkeypatch.setattr(
        operator_auth.jwt, "decode",
        lambda *args, **kwargs: {
            "sub": "stable-provider-subject", "email": "Operator@PUBBA.test",
            "iss": "https://issuer.example", "iat": 1, "exp": 2,
        },
    )
    identity = verify_oidc_token("verified-token")
    assert identity.subject == "stable-provider-subject"
    assert identity.email == "operator@pubba.test"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (jwt.InvalidIssuerError("issuer"), "Invalid or expired"),
        (jwt.InvalidAudienceError("audience"), "Invalid or expired"),
        (jwt.ExpiredSignatureError("expired"), "Invalid or expired"),
        (jwt.InvalidSignatureError("forged"), "Invalid or expired"),
    ],
)
def test_oidc_invalid_credentials_fail_closed(monkeypatch, error, expected):
    monkeypatch.setenv("OPERATOR_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("OPERATOR_OIDC_AUDIENCE", "pubba-api")
    monkeypatch.setattr(
        operator_auth, "_jwks_client",
        lambda issuer: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key="key")),
    )
    monkeypatch.setattr(operator_auth.jwt, "decode", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(OperatorAuthError, match=expected):
        verify_oidc_token("untrusted")


def test_auth_rollout_modes_preserve_legacy_switch(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "shadow")
    assert operator_auth_mode() == "shadow"
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "off")
    assert operator_auth_mode() == "off"
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "enforce")
    assert operator_auth_mode() == "enforce"
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "invalid")
    with pytest.raises(OperatorAuthError):
        operator_auth_mode()


@pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
def test_cross_portfolio_history_is_hidden(monkeypatch, role):
    configure_auth(monkeypatch, role=role)
    monkeypatch.setenv("OPERATOR_PORTFOLIO_RBAC_ENABLED", "true")
    monkeypatch.setattr(main, "list_operator_portfolios", lambda operator_id: [
        {"portfolio_id": OTHER_PORTFOLIO, "active": True}
    ])
    response = TestClient(main.app).get(
        f"/recommendations/history?portfolio_id={PORTFOLIO_ID}", headers=AUTH_HEADERS
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "portfolio_not_found"


def test_admin_has_explicit_global_portfolio_behavior(monkeypatch):
    configure_auth(monkeypatch, role="admin")
    monkeypatch.setenv("OPERATOR_PORTFOLIO_RBAC_ENABLED", "true")
    monkeypatch.setattr(main, "list_recommendation_history", lambda **kwargs: [])
    response = TestClient(main.app).get(
        f"/recommendations/history?portfolio_id={PORTFOLIO_ID}", headers=AUTH_HEADERS
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("role", "path"),
    [
        ("operator", "link-simulation"),
        ("approver", "link-dispatch"),
    ],
)
def test_cross_portfolio_linking_is_denied_before_object_lookup(monkeypatch, role, path):
    configure_workflow_storage(monkeypatch, role=role)
    monkeypatch.setenv("OPERATOR_PORTFOLIO_RBAC_ENABLED", "true")
    monkeypatch.setattr(main, "get_operator_portfolio_access", lambda *args: None)
    monkeypatch.setattr(
        main, "get_simulation_result",
        lambda value: (_ for _ in ()).throw(AssertionError("unauthorized lookup occurred")),
    )
    monkeypatch.setattr(
        main, "get_dispatch_event_record",
        lambda value: (_ for _ in ()).throw(AssertionError("unauthorized lookup occurred")),
    )
    response = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/{path}",
        json={"record_id": "33333333-3333-3333-3333-333333333333"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def test_transactional_rpc_failure_does_not_fall_back_to_business_write(monkeypatch):
    persisted, _ = configure_workflow_storage(monkeypatch, role="operator")
    monkeypatch.setenv("OPERATOR_TRANSACTIONAL_AUDIT_ENABLED", "true")
    monkeypatch.setattr(
        main, "transactional_operator_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SupabaseError("transaction rolled back", error_code="transaction_failed")
        ),
    )
    monkeypatch.setattr(
        main, "update_recommendation_links",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("non-atomic fallback used")),
    )
    response = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/acknowledge",
        json={"note": "reviewed"}, headers=AUTH_HEADERS,
    )
    assert response.status_code == 502
    assert persisted.get("acknowledged_at") is None


def test_dashboard_portfolio_context_is_sent_to_backend():
    class Response:
        ok = True
        status_code = 200
        def json(self): return {"records": []}
    class Session:
        def __init__(self): self.kwargs = None
        def request(self, *args, **kwargs): self.kwargs = kwargs; return Response()
    session = Session()
    client = Only1ApiClient("https://api.example.test", session=session)
    client.set_portfolio_context(PORTFOLIO_ID)
    assert client.get_recommendation_history() == []
    assert session.kwargs["params"]["portfolio_id"] == PORTFOLIO_ID


def test_overview_assets_are_filtered_by_authorized_portfolio(monkeypatch):
    configure_auth(monkeypatch, role="viewer")
    monkeypatch.setenv("OPERATOR_PORTFOLIO_RBAC_ENABLED", "true")
    monkeypatch.setattr(main, "list_operator_portfolios", lambda operator_id: [
        {"portfolio_id": PORTFOLIO_ID, "active": True}
    ])
    captured = {}
    monkeypatch.setattr(
        main, "get_asset_performance",
        lambda **kwargs: captured.update(kwargs) or [],
    )
    response = TestClient(main.app).get(
        f"/portfolio/assets?portfolio_id={PORTFOLIO_ID}", headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    assert captured["portfolio_id"] == PORTFOLIO_ID


def test_new_migration_is_additive_scoped_and_transactional():
    sql = Path("supabase/migrations/202607180003_portfolio_rbac_transactional_audit.sql").read_text()
    assert "create table if not exists public.operator_portfolio_access" in sql
    assert "enable row level security" in sql
    assert "pubba_require_portfolio_role" in sql
    for action in ("recommendation_capture", "recommendation_action", "operator_update", "portfolio_access_change"):
        assert f"pubba_audited_{action}" in sql
    assert "security definer" in sql
    assert "grant execute" in sql
    assert "pubba_effective_portfolio_role(uuid,uuid) from public" in sql
    assert "drop table" not in sql.lower()


def test_bootstrap_requires_verified_subject_and_prevents_second_admin():
    source = Path("scripts/bootstrap_first_admin.py").read_text()
    assert "--confirm-first-admin" in source
    assert "@\" in args.subject" in source
    assert "An Admin already exists" in source
    assert '"role": "admin"' in source
    assert '"--execute"' in source


def test_bootstrap_defaults_to_no_write_dry_run(monkeypatch, capsys):
    import scripts.bootstrap_first_admin as bootstrap

    monkeypatch.setattr(bootstrap, "get_operator_by_subject", lambda subject: None)
    monkeypatch.setattr(bootstrap, "list_operators", lambda **kwargs: [])
    monkeypatch.setattr(
        bootstrap, "create_operator",
        lambda fields: (_ for _ in ()).throw(AssertionError("dry run inserted operator")),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["bootstrap_first_admin.py", "--subject", "provider-sub-123",
         "--email", "admin@pubba.test", "--display-name", "Admin",
         "--confirm-first-admin"],
    )
    assert bootstrap.main() == 0
    assert "no operator was created" in capsys.readouterr().out


def test_streamlit_has_no_direct_supabase_access():
    for path in Path("dashboard").rglob("*.py"):
        source = path.read_text()
        assert "import supabase" not in source
        assert "from supabase import" not in source
