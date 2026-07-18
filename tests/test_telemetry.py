from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
import supabase
from dashboard.charts import telemetry_history_figure
from dashboard.components import render_asset_cards
from dashboard.api_client import DashboardApiError
from dashboard.refresh import refresh_dashboard_data
from services.dashboard_summary import build_dashboard_summary
from services.telemetry import (
    TelemetryValidationError,
    calculate_dispatch_readiness,
    generate_development_telemetry,
    normalize_telemetry,
    telemetry_freshness,
)


NOW = datetime(2026, 7, 17, 20, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def telemetry(**values):
    record = {
        "asset_id": "BAT-001",
        "recorded_at": "2026-07-17T19:55:00Z",
        "state_of_charge_pct": 78,
        "current_power_mw": 1.5,
        "available_charge_power_mw": 4.0,
        "available_discharge_power_mw": 8.5,
        "available_energy_mwh": 31.2,
        "temperature_c": 27,
        "operational_status": "normal",
        "availability_status": "available",
        "telemetry_source": "scada_gateway",
        "is_simulated": False,
    }
    record.update(values)
    return record


def test_telemetry_validation_preserves_partial_nulls_without_zeroes():
    result = normalize_telemetry(
        telemetry(current_power_mw=None, temperature_c=None), now=NOW
    )
    assert result["current_power_mw"] is None
    assert result["temperature_c"] is None
    assert result["is_simulated"] is False


def test_telemetry_migration_is_additive_indexed_and_constrained():
    sql = (ROOT / "supabase/migrations/202607170001_battery_telemetry_foundation.sql").read_text()
    assert "create table if not exists public.asset_telemetry" in sql
    assert "foreign key (asset_id) references public.assets(asset_id)" in sql
    assert "state_of_charge_pct between 0 and 100" in sql
    assert "asset_telemetry_latest_idx" in sql
    assert "view public.latest_asset_telemetry" in sql
    assert "drop table" not in sql.lower()


@pytest.mark.parametrize("soc", [-0.1, 100.1])
def test_soc_outside_zero_to_one_hundred_is_rejected(soc):
    with pytest.raises(TelemetryValidationError, match="state_of_charge_pct"):
        normalize_telemetry(telemetry(state_of_charge_pct=soc), now=NOW)


def test_future_and_timezone_naive_timestamps_are_rejected():
    with pytest.raises(TelemetryValidationError, match="future"):
        normalize_telemetry(
            telemetry(recorded_at=(NOW + timedelta(minutes=2)).isoformat()), now=NOW
        )
    with pytest.raises(TelemetryValidationError, match="timezone offset"):
        normalize_telemetry(telemetry(recorded_at="2026-07-17T19:55:00"), now=NOW)


def test_negative_available_power_is_rejected_but_signed_current_power_is_valid():
    result = normalize_telemetry(telemetry(current_power_mw=-3), now=NOW)
    assert result["current_power_mw"] == -3
    with pytest.raises(TelemetryValidationError):
        normalize_telemetry(telemetry(available_charge_power_mw=-1), now=NOW)


def test_dispatch_readiness_states_are_explainable():
    assert calculate_dispatch_readiness(telemetry(), now=NOW).state == "ready_charge_discharge"
    assert calculate_dispatch_readiness(
        telemetry(available_charge_power_mw=0), now=NOW
    ).state == "ready_to_discharge"
    assert calculate_dispatch_readiness(
        telemetry(operational_status="maintenance"), now=NOW
    ).state == "unavailable"
    assert calculate_dispatch_readiness(
        telemetry(recorded_at="2026-07-17T19:00:00Z"), now=NOW
    ).state == "telemetry_stale"
    assert calculate_dispatch_readiness(None, now=NOW).state == "telemetry_unavailable"
    assert calculate_dispatch_readiness(
        telemetry(state_of_charge_pct=None), now=NOW
    ).state == "limited"


def test_stale_telemetry_reports_age():
    result = telemetry_freshness("2026-07-17T19:00:00Z", now=NOW)
    assert result == {"status": "stale", "age_seconds": 3600, "stale": True}


def test_development_generator_is_disabled_and_deterministic(monkeypatch):
    monkeypatch.delenv("PUBBA_ENABLE_SIMULATED_TELEMETRY", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        generate_development_telemetry("BAT-001", recorded_at=NOW, seed=7)
    monkeypatch.setenv("PUBBA_ENABLE_SIMULATED_TELEMETRY", "true")
    first = generate_development_telemetry("BAT-001", recorded_at=NOW, seed=7)
    second = generate_development_telemetry("BAT-001", recorded_at=NOW, seed=7)
    assert first == second
    assert first["is_simulated"] is True
    assert first["telemetry_source"] == "development_generator"


def test_supabase_latest_history_and_portfolio_ordering(monkeypatch):
    monkeypatch.setattr(supabase, "get_asset", lambda asset_id: {"asset_id": asset_id})
    captured = []
    monkeypatch.setattr(
        supabase, "_request",
        lambda method, table, **kwargs: captured.append(kwargs["params"]) or [telemetry()],
    )
    assert supabase.get_latest_telemetry("BAT-001")["asset_id"] == "BAT-001"
    assert captured[-1]["order"] == "recorded_at.desc,id.desc"
    records = supabase.list_telemetry_history(
        "BAT-001", start_at=NOW - timedelta(hours=1), end_at=NOW, limit=50
    )
    assert records
    assert captured[-1]["order"] == "recorded_at.asc,id.asc"


def test_portfolio_latest_uses_index_backed_latest_view(monkeypatch):
    monkeypatch.setattr(supabase, "get_default_portfolio", lambda: {"id": "portfolio"})
    captured = {}
    monkeypatch.setattr(
        supabase, "_list_all",
        lambda table, params: captured.update(table=table, params=params) or [
            telemetry(id="new"), telemetry(id="other", asset_id="BAT-002")
        ],
    )
    result = supabase.list_portfolio_latest_telemetry()
    assert [row["id"] for row in result] == ["new", "other"]
    assert captured["table"] == "latest_asset_telemetry"
    assert captured["params"]["order"] == "asset_id.asc"


def test_dashboard_summary_adds_telemetry_without_breaking_existing_contract():
    portfolio = {
        "id": "portfolio", "code": "ONLY1", "name": "PUBBA Power",
        "default_market": "CAISO", "reporting_timezone": "UTC", "currency_code": "USD",
    }
    result = build_dashboard_summary(
        now=NOW, include_market=False,
        portfolio_resolver=lambda: portfolio,
        records_loader=lambda _: ([{
            "id": "asset", "status": "active", "power_mw": 10,
            "energy_mwh": 40, "updated_at": "2026-07-17T19:00:00Z",
        }], []),
        market_loader=lambda **kwargs: pd.DataFrame(),
        telemetry_loader=lambda: [telemetry()],
    )
    assert result["telemetry"]["status"] == "available"
    assert result["telemetry"]["average_state_of_charge_pct"] == 78
    assert result["kpis"]["battery_state_of_charge_pct"] == 78
    assert result["telemetry"]["assets_ready_to_discharge"] == 1


def test_dashboard_summary_ignores_malformed_telemetry():
    portfolio = {
        "id": "portfolio", "code": "ONLY1", "name": "PUBBA Power",
        "default_market": "CAISO", "reporting_timezone": "UTC", "currency_code": "USD",
    }
    result = build_dashboard_summary(
        now=NOW, include_market=False, portfolio_resolver=lambda: portfolio,
        records_loader=lambda _: ([], []), telemetry_loader=lambda: [telemetry(state_of_charge_pct=120)],
    )
    assert result["telemetry"]["status"] == "unavailable"


def test_telemetry_chart_handles_one_point_and_empty_history():
    one = telemetry_history_figure([telemetry()])
    empty = telemetry_history_figure([])
    assert one.data[0].mode == "markers"
    assert one.data[0].connectgaps is False
    assert len(empty.data) == 0


def test_asset_cards_render_with_and_without_telemetry():
    class St:
        html = ""
        def markdown(self, value, **kwargs):
            self.html += value

    st = St()
    render_asset_cards(st, [{
        "name": "Battery", "technology": "LFP", "location": "CAISO",
        "status": "ready to discharge", "soc": {"value": 78, "label": "78.0%"},
        "metrics": [("Readiness", "Ready to discharge")],
    }])
    assert 'role="progressbar"' in st.html
    assert "78.0%" in st.html
    st_without = St()
    render_asset_cards(st_without, [{
        "name": "Battery", "technology": "LFP", "location": "CAISO",
        "status": "active", "soc": None,
        "metrics": [("State of charge", "Telemetry unavailable")],
    }])
    assert 'role="progressbar"' not in st_without.html
    assert "Telemetry unavailable" in st_without.html


def test_telemetry_history_api_failure_does_not_hide_dashboard_data():
    class Client:
        last_latency_ms = 1
        def get_dashboard_summary(self, **kwargs):
            return {"telemetry": {"assets": [{"asset_id": "BAT-001"}]}}
        def get_portfolio_assets(self):
            return [{"asset_id": "BAT-001"}]
        def get_telemetry_history(self, asset_id):
            raise DashboardApiError("Telemetry unavailable")

    payload, error = refresh_dashboard_data({}, Client())
    assert error is None
    assert payload["assets"][0]["asset_id"] == "BAT-001"
    assert payload["telemetry_history"] == []
    assert payload["telemetry_error"] == "Telemetry unavailable"


def test_telemetry_routes_and_write_gate(monkeypatch):
    monkeypatch.setattr(main, "get_latest_telemetry", lambda asset_id: telemetry(asset_id=asset_id))
    monkeypatch.setattr(main, "list_telemetry_history", lambda *args, **kwargs: [telemetry()])
    monkeypatch.setattr(main, "list_portfolio_latest_telemetry", lambda: [telemetry()])
    client = TestClient(main.app)
    assert client.get("/telemetry/assets/BAT-001/latest").status_code == 200
    assert client.get("/telemetry/assets/BAT-001/history").json()["records"][0]["asset_id"] == "BAT-001"
    assert client.get("/telemetry/portfolio/latest").json()["telemetry_status"] == "available"
    assert client.post("/telemetry", json=telemetry()).status_code == 403


def test_telemetry_post_validates_and_persists_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEMETRY_WRITES_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_WRITE_TOKEN", "secret")
    monkeypatch.setattr(main, "create_telemetry", lambda record: record)
    monkeypatch.setattr(main, "get_latest_telemetry_for_source", lambda source: None)
    response = TestClient(main.app).post(
        "/telemetry", json=telemetry(), headers={"X-Telemetry-Key": "secret"}
    )
    assert response.status_code == 201
    assert response.json()["record"]["telemetry_source"] == "scada_gateway"


def test_telemetry_write_requires_token_even_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEMETRY_WRITES_ENABLED", "true")
    monkeypatch.delenv("TELEMETRY_WRITE_TOKEN", raising=False)
    assert TestClient(main.app).post("/telemetry", json=telemetry()).status_code == 403
