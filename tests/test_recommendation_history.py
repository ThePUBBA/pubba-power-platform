from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
import supabase
from services.recommendation_history import (
    decision_timeline,
    evaluate_outcome,
    history_analytics,
    history_detail,
    recommendation_snapshot,
)
from services.recommendations import RECOMMENDATION_ENGINE_VERSION


NOW = datetime(2026, 7, 18, 3, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-1111-1111-1111-111111111111"
RECOMMENDATION_ID = "22222222-2222-2222-2222-222222222222"
SIMULATION_ID = "33333333-3333-3333-3333-333333333333"
DISPATCH_ID = "44444444-4444-4444-4444-444444444444"


def current_recommendation():
    return {
        "asset_id": "BAT-1", "asset_name": "Battery One",
        "market_price_per_mwh": 100, "market_status": "fresh",
        "market_timestamp": "2026-07-18T02:55:00Z",
        "opportunity_score": 88, "recommendation": "Strong discharge opportunity",
        "recommendation_direction": "discharge",
        "estimated_economics": {
            "estimated_charging_cost": 1000,
            "estimated_discharge_revenue": 4000,
            "estimated_gross_profit": 3000,
            "estimated_margin_pct": 75,
            "break_even_discharge_price_per_mwh": 25,
            "estimated_spread_per_mwh": 75,
        },
        "operational_readiness": {
            "state": "telemetry_unavailable",
            "explanation": "Operational readiness awaiting live telemetry.",
        },
        "telemetry_available": False, "telemetry_timestamp": None,
        "primary_drivers": ["High price"], "risks": ["No live telemetry"],
        "missing_operational_data": ["live state of charge"],
        "explanation": "Strong discharge score 88/100.",
        "assumptions": {"round_trip_efficiency": 0.8, "variable_om_per_mwh": 0},
        "simulation_inputs": {"location": "NODE"},
        "generated_at": "2026-07-18T03:00:00Z",
        "recommendation_engine_version": RECOMMENDATION_ENGINE_VERSION,
    }


def history_record(**updates):
    value = {
        "id": RECOMMENDATION_ID, "portfolio_id": PORTFOLIO_ID,
        "asset_id": "BAT-1", "generated_at": "2026-07-18T03:00:00Z",
        "captured_at": "2026-07-18T03:01:00Z", "market_price": 100,
        "opportunity_score": 88, "recommendation": "Strong discharge opportunity",
        "recommendation_direction": "discharge", "estimated_charging_cost": 1000,
        "estimated_discharge_revenue": 4000, "estimated_gross_profit": 3000,
        "estimated_margin": 75, "recommendation_engine_version": "1.0",
        "drivers": ["High price"], "risks": [], "missing_operational_inputs": [],
        "simulation_id": None, "dispatch_id": None,
    }
    value.update(updates)
    return value


def configure_identity(monkeypatch, role="operator", status="active"):
    monkeypatch.setattr(
        main, "verify_oidc_token",
        lambda token: SimpleNamespace(subject="oidc-user-1", email="operator@pubba.test"),
    )
    monkeypatch.setattr(main, "get_operator_by_subject", lambda subject: {
        "id": "55555555-5555-5555-5555-555555555555",
        "auth_subject": subject, "email": "operator@pubba.test",
        "display_name": "Test Operator", "role": role, "status": status,
    })
    return {"Authorization": "Bearer signed-oidc-token"}


def simulation(**updates):
    value = {
        "id": SIMULATION_ID, "portfolio_id": PORTFOLIO_ID, "asset_id": "BAT-1",
        "estimated_net_margin": 2800, "created_at": "2026-07-18T03:05:00Z",
    }
    value.update(updates)
    return value


def dispatch(**updates):
    value = {
        "id": DISPATCH_ID, "portfolio_id": PORTFOLIO_ID, "asset_id": "BAT-1",
        "status": "completed", "discharge_revenue": 3900,
        "charging_cost": 1100, "net_profit": 2600,
        "updated_at": "2026-07-18T05:00:00Z",
    }
    value.update(updates)
    return value


def test_migration_is_additive_indexed_rls_and_snapshot_immutable():
    sql = Path("supabase/migrations/202607180001_recommendation_history.sql").read_text()
    assert "create table if not exists public.recommendation_history" in sql
    assert "foreign key (portfolio_id) references public.portfolios(id)" in sql
    assert "foreign key (asset_id) references public.assets(asset_id)" in sql
    assert "foreign key (simulation_id) references public.simulation_results(id)" in sql
    assert "foreign key (dispatch_id) references public.dispatch_events(id)" in sql
    assert "enforce_recommendation_snapshot_immutability" in sql
    assert "enable row level security" in sql
    assert "drop table" not in sql.lower()


def test_snapshot_is_versioned_stable_and_preserves_structured_explanation():
    first = recommendation_snapshot(
        current_recommendation(), portfolio_id=PORTFOLIO_ID,
        asset={"lease_cost_monthly": 300},
    )
    second = recommendation_snapshot(
        {**current_recommendation(), "generated_at": "2026-07-18T03:02:00Z"}, portfolio_id=PORTFOLIO_ID,
        asset={"lease_cost_monthly": 300},
    )
    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert first["recommendation_engine_version"] == RECOMMENDATION_ENGINE_VERSION
    assert first["drivers"] == ["High price"]
    assert first["lease_cost_assumption"] == 300


def test_outcome_states_and_variance_do_not_fabricate_values():
    no_action = evaluate_outcome(history_record())
    simulation_only = evaluate_outcome(history_record(), simulation=simulation())
    completed = evaluate_outcome(history_record(), dispatch=dispatch())
    unavailable = evaluate_outcome(
        history_record(), dispatch=dispatch(discharge_revenue=None, charging_cost=None, net_profit=None)
    )
    assert no_action["status"] == "no_action_taken"
    assert simulation_only["status"] == "simulation_only"
    assert completed["status"] == "dispatch_completed"
    assert completed["variance"]["profit"]["absolute"] == -400
    assert completed["variance"]["profit"]["percentage_error"] == -400 / 3000 * 100
    assert unavailable["status"] == "outcome_unavailable"
    assert unavailable["realized"]["profit"] is None


def test_decision_timeline_contains_only_backed_events():
    record = history_record(
        simulation_id=SIMULATION_ID, simulation_linked_at="2026-07-18T03:06:00Z",
        dispatch_id=DISPATCH_ID, dispatch_linked_at="2026-07-18T03:10:00Z",
        acknowledged_at="2026-07-18T03:02:00Z",
        acknowledgement_attribution="authenticated_operator_workflow",
    )
    events = decision_timeline(record, simulation=simulation(), dispatch=dispatch())
    assert [item["event"] for item in events] == [
        "recommendation_generated", "recommendation_captured",
        "recommendation_acknowledged", "simulation_linked", "dispatch_linked",
        "dispatch_completed",
    ]
    assert "simulation_reviewed" not in {item["event"] for item in events}


def test_history_analytics_displays_sample_size_without_accuracy_claim():
    detail = history_detail(history_record(dispatch_id=DISPATCH_ID), dispatch=dispatch())
    analytics = history_analytics([detail])
    assert analytics["sample_size"] == 1
    assert analytics["linked_outcome_sample_size"] == 1
    assert analytics["realized_profit"] == 2600
    assert analytics["accuracy_available"] is False


def test_supabase_history_filters_are_forwarded_without_recomputation(monkeypatch):
    captured = {}
    def request(method, table, params=None, **kwargs):
        captured.update(params)
        return []
    monkeypatch.setattr(supabase, "_request", request)
    supabase.list_recommendation_history(
        portfolio_id=PORTFOLIO_ID, asset_id="BAT-1", direction="discharge",
        start_at=NOW - timedelta(days=1), end_at=NOW, minimum_score=70,
        linked_simulation=True, linked_dispatch=False,
    )
    assert captured["portfolio_id"] == f"eq.{PORTFOLIO_ID}"
    assert captured["asset_id"] == "eq.BAT-1"
    assert captured["recommendation_direction"] == "eq.discharge"
    assert captured["opportunity_score"] == "gte.70"
    assert captured["simulation_id"] == "not.is.null"
    assert captured["dispatch_id"] == "is.null"
    assert "and" in captured


def configure_capture(monkeypatch, *, duplicate=None):
    market_time = datetime.now(timezone.utc).isoformat()
    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")
    configure_identity(monkeypatch)
    monkeypatch.setattr(main, "build_dashboard_summary", lambda **kwargs: {
        "metadata": {"market_location": "NODE", "market_type": "RTM", "market_updated_at": market_time},
        "status": {"market_data": "connected"}, "kpis": {"current_market_price_per_mwh": 100},
        "series": {"market_prices": [{"timestamp": market_time, "price_per_mwh": 100}]},
        "telemetry": {"assets": []},
    })
    monkeypatch.setattr(main, "get_asset_performance", lambda: [{
        "asset_id": "BAT-1", "asset_name": "Battery One", "status": "active",
        "power_mw": 10, "energy_mwh": 40, "duration_hours": 4,
        "lease_cost_monthly": 0, "location": "NODE",
    }])
    monkeypatch.setattr(main, "get_default_portfolio", lambda: {"id": PORTFOLIO_ID})
    monkeypatch.setattr(main, "get_asset", lambda asset_id: {
        "asset_id": asset_id, "portfolio_id": PORTFOLIO_ID, "lease_cost_monthly": 0,
    })
    monkeypatch.setattr(main, "find_recent_recommendation_capture", lambda **kwargs: duplicate)
    monkeypatch.setattr(main, "create_recommendation_capture", lambda fields: {"id": RECOMMENDATION_ID, **fields})
    monkeypatch.setattr(main, "create_operator_audit_event", lambda fields: {"id": "audit-1", **fields})


def test_capture_requires_explicit_authorization_and_deduplicates(monkeypatch):
    configure_capture(monkeypatch)
    client = TestClient(main.app)
    assert client.post("/recommendations/BAT-1/capture").status_code == 401
    captured = client.post(
        "/recommendations/BAT-1/capture",
        headers={"Authorization": "Bearer signed-oidc-token"},
    )
    assert captured.status_code == 201
    assert captured.json()["recommendation"]["recommendation_engine_version"] == "1.0"

    configure_capture(monkeypatch, duplicate=history_record())
    duplicate = client.post(
        "/recommendations/BAT-1/capture",
        headers={"Authorization": "Bearer signed-oidc-token"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["capture_status"] == "duplicate"


def test_recommendation_gets_never_call_capture(monkeypatch):
    monkeypatch.setattr(main, "build_dashboard_summary", lambda **kwargs: {
        "metadata": {}, "status": {"market_data": "unavailable"}, "kpis": {},
        "series": {}, "telemetry": {"assets": []},
    })
    monkeypatch.setattr(main, "get_asset_performance", lambda: [])
    monkeypatch.setattr(
        main, "create_recommendation_capture",
        lambda fields: (_ for _ in ()).throw(AssertionError("GET persisted history")),
    )
    assert TestClient(main.app).get("/recommendations/portfolio").status_code == 200


def configure_history_links(monkeypatch, role="operator"):
    monkeypatch.setenv("RECOMMENDATION_WRITES_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_RBAC_STORAGE_ENABLED", "true")
    configure_identity(monkeypatch, role=role)
    persisted = history_record()
    monkeypatch.setattr(main, "get_recommendation_history", lambda value: dict(persisted))
    monkeypatch.setattr(main, "get_simulation_result", lambda value: None)
    monkeypatch.setattr(main, "get_dispatch_event_record", lambda value: None)
    def update(value, fields):
        persisted.update(fields)
        return dict(persisted)
    monkeypatch.setattr(main, "update_recommendation_links", update)
    monkeypatch.setattr(main, "get_recommendation_approval", lambda value: None)
    monkeypatch.setattr(main, "list_operator_audit_events", lambda **kwargs: [])
    monkeypatch.setattr(main, "create_operator_audit_event", lambda fields: {"id": "audit-1", **fields})


def test_history_retrieval_empty_and_unknown_id(monkeypatch):
    monkeypatch.setattr(main, "list_recommendation_history", lambda **kwargs: [])
    client = TestClient(main.app)
    assert client.get("/recommendations/history").json()["records"] == []
    monkeypatch.setattr(main, "get_recommendation_history", lambda value: None)
    assert client.get(f"/recommendations/history/{RECOMMENDATION_ID}").status_code == 404


def test_history_outcome_filter_is_api_backed(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main, "list_recommendation_history",
        lambda **kwargs: captured.update(kwargs) or [],
    )
    response = TestClient(main.app).get(
        "/recommendations/history?outcome_status=simulation_only"
    )
    assert response.status_code == 200
    assert captured["linked_simulation"] is True
    assert captured["linked_dispatch"] is False
    invalid = TestClient(main.app).get(
        "/recommendations/history?outcome_status=unknown"
    )
    assert invalid.status_code == 400


def test_simulation_candidates_use_default_portfolio_and_asset(monkeypatch):
    monkeypatch.setattr(main, "get_default_portfolio", lambda: {"id": PORTFOLIO_ID})
    captured = {}
    monkeypatch.setattr(
        main, "list_simulation_results",
        lambda **kwargs: captured.update(kwargs) or [{"id": SIMULATION_ID}],
    )
    response = TestClient(main.app).get("/simulations?asset_id=BAT-1&limit=25")
    assert response.status_code == 200
    assert response.json()[0]["id"] == SIMULATION_ID
    assert captured == {
        "portfolio_id": PORTFOLIO_ID, "asset_id": "BAT-1",
        "limit": 25, "offset": 0,
    }


def test_simulation_link_is_explicit_and_validated(monkeypatch):
    configure_history_links(monkeypatch)
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer signed-oidc-token"}
    missing = client.post(
        f"/recommendations/history/{RECOMMENDATION_ID}/link-simulation",
        json={"record_id": SIMULATION_ID}, headers=headers,
    )
    assert missing.status_code == 404
    monkeypatch.setattr(main, "get_simulation_result", lambda value: simulation())
    linked = client.post(
        f"/recommendations/history/{RECOMMENDATION_ID}/link-simulation",
        json={"record_id": SIMULATION_ID}, headers=headers,
    )
    assert linked.status_code == 200
    assert linked.json()["simulation_id"] == SIMULATION_ID


def test_dispatch_link_calculates_realized_outcome(monkeypatch):
    configure_history_links(monkeypatch, role="approver")
    monkeypatch.setattr(main, "get_dispatch_event_record", lambda value: dispatch())
    linked = TestClient(main.app).post(
        f"/recommendations/history/{RECOMMENDATION_ID}/link-dispatch",
        json={"record_id": DISPATCH_ID},
        headers={"Authorization": "Bearer signed-oidc-token"},
    )
    assert linked.status_code == 200
    assert linked.json()["outcome"]["status"] == "dispatch_completed"
    assert linked.json()["outcome"]["variance"]["profit"]["absolute"] == -400


def test_history_database_outage_is_structured(monkeypatch):
    monkeypatch.setattr(
        main, "list_recommendation_history",
        lambda **kwargs: (_ for _ in ()).throw(
            main.SupabaseError("unavailable", error_code="supabase_unavailable", status_code=503)
        ),
    )
    response = TestClient(main.app).get("/recommendations/history")
    assert response.status_code == 503
    assert response.json()["error_code"] == "supabase_unavailable"
