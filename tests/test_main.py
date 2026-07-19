import csv
from datetime import datetime, timedelta, timezone
from io import StringIO

from fastapi.testclient import TestClient
import pandas as pd


def make_lmp_frame(prices):
    start = datetime(2025, 4, 1, tzinfo=timezone.utc)
    rows = []
    for index, price in enumerate(prices):
        interval_start = start + timedelta(hours=index)
        interval_end = interval_start + timedelta(hours=1)
        rows.append(
            {
                "interval_start_gmt": interval_start.isoformat(),
                "interval_end_gmt": interval_end.isoformat(),
                "node_id_xml": "TH_NP15_GEN-APND",
                "market_run_id": "RTM",
                "lmp_prc": price,
            }
        )
    return pd.DataFrame(rows)


def test_fastapi_application_imports_successfully():
    import main

    assert main.app is not None


def test_lmp_endpoint_returns_json_serializable_records(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        return make_lmp_frame([22.42])

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get(
        "/lmp",
        params={
            "market": "RTM",
            "location": "TH_NP15_GEN-APND",
            "date": "2025-04-01",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["lmp_prc"] == 22.42


def test_lmp_endpoint_maps_invalid_input_to_400(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise ValueError("date must use ISO format YYYY-MM-DD")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/lmp", params={"date": "bad"})

    assert response.status_code == 400
    assert response.json() == {
        "error_code": "invalid_request",
        "message": "date must use ISO format YYYY-MM-DD",
        "field": "date",
    }


def test_lmp_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/lmp")

    assert response.status_code == 502
    assert response.json() == {
        "error_code": "upstream_service_error",
        "message": "CAISO OASIS request timed out",
        "upstream_service": "CAISO OASIS",
    }


def test_arbitrage_endpoint_returns_expected_analysis(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        return make_lmp_frame([100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85])

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get(
        "/arbitrage",
        params={
            "market": "RTM",
            "location": "TH_NP15_GEN-APND",
            "date": "2025-04-01",
            "duration_hours": 4,
            "round_trip_efficiency": 0.80,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["charging_window"]["start_timestamp"] == "2025-04-01T02:00:00+00:00"
    assert body["discharging_window"]["start_timestamp"] == "2025-04-01T08:00:00+00:00"
    assert body["estimated_gross_margin_per_mwh_discharged"] == 71.25


def test_arbitrage_endpoint_rejects_invalid_efficiency(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        return make_lmp_frame([1, 2, 3, 4])

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get(
        "/arbitrage",
        params={"duration_hours": 1, "round_trip_efficiency": 0},
    )

    assert response.status_code == 400
    assert response.json()["field"] == "round_trip_efficiency"


def test_arbitrage_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/arbitrage")

    assert response.status_code == 502
    assert response.json()["error_code"] == "upstream_service_error"


def test_simulate_endpoint_returns_expected_profit(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        return make_lmp_frame([100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85])

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get(
        "/simulate",
        params={
            "market": "RTM",
            "location": "TH_NP15_GEN-APND",
            "date": "2025-04-01",
            "power_mw": 10,
            "duration_hours": 4,
            "round_trip_efficiency": 0.80,
            "cycles": 1,
            "storage_fee_per_mwh": 5,
            "variable_om_per_mwh": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["energy_capacity_mwh"] == 40
    assert body["charging_energy_required_mwh"] == 50
    assert body["discharged_energy_mwh"] == 40
    assert body["charging_cost"] == 750
    assert body["discharge_revenue"] == 3600
    assert body["estimated_net_margin"] == 2570
    assert body["net_margin_per_mw"] == 257
    assert body["net_margin_per_mwh_discharged"] == 64.25
    assert body["charging_window"]["start_timestamp"] == "2025-04-01T02:00:00+00:00"
    assert body["discharging_window"]["start_timestamp"] == "2025-04-01T08:00:00+00:00"


def test_simulate_endpoint_rejects_invalid_power(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        return make_lmp_frame([1, 2, 3, 4])

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/simulate", params={"power_mw": 0, "duration_hours": 1})

    assert response.status_code in (400, 422)
    assert response.json()["field"] == "power_mw"


def test_simulate_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/simulate", params={"power_mw": 10})

    assert response.status_code == 502
    assert response.json() == {
        "error_code": "upstream_service_error",
        "message": "CAISO OASIS request timed out",
        "upstream_service": "CAISO OASIS",
    }


def simulation_payload(**overrides):
    payload = {
        "location": "TH_NP15_GEN-APND",
        "market": "RTM",
        "date": "2025-04-01",
        "power_mw": 10,
        "duration_hours": 4,
        "round_trip_efficiency": 0.8,
        "cycles": 1,
        "storage_fee_per_mwh": 5,
        "variable_om_per_mwh": 2,
    }
    payload.update(overrides)
    return payload


def test_post_simulate_returns_expected_profit(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )

    response = TestClient(main.app).post("/simulate", json=simulation_payload())

    assert response.status_code == 200
    assert response.json()["estimated_net_margin"] == 2570


def test_post_simulate_persists_to_supabase_with_idempotency_key(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    captured = {}

    def persist(request_fields, result, idempotency_key):
        captured.update(
            request_fields=request_fields,
            result=result,
            idempotency_key=idempotency_key,
        )
        return {
            "status": "saved",
            "simulation_id": "sim-1",
            "dispatch_id": None,
            "error_code": None,
            "message": "Simulation saved",
        }

    monkeypatch.setattr(main, "persist_simulation", persist)
    response = TestClient(main.app).post(
        "/simulate",
        json=simulation_payload(),
        headers={"Idempotency-Key": "retool-run-1"},
    )

    assert response.status_code == 200
    assert captured["idempotency_key"] == "retool-run-1"
    assert captured["request_fields"]["market"] == "RTM"
    assert captured["result"]["estimated_net_margin"] == 2570
    assert response.json()["persistence"]["status"] == "saved"


def test_post_simulate_exposes_partial_supabase_failure(monkeypatch, caplog):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    monkeypatch.setattr(
        main,
        "persist_simulation",
        lambda *args: (_ for _ in ()).throw(
            main.SupabaseError(
                "Simulation saved, but dispatch creation failed",
                error_code="failed_dispatch_creation",
                operation="create_dispatch",
                simulation_id="sim-1",
            )
        ),
    )

    response = TestClient(main.app).post(
        "/simulate", json=simulation_payload(asset_id="BAT-001")
    )

    assert response.status_code == 200
    assert response.json()["estimated_net_margin"] == 2570
    assert response.json()["persistence"] == {
        "status": "partial",
        "simulation_id": "sim-1",
        "dispatch_id": None,
        "error_code": "failed_dispatch_creation",
        "message": "Simulation saved, but dispatch creation failed",
    }
    assert "Supabase ledger persistence failed" in caplog.text


def test_post_simulate_rejects_invalid_request_body():
    import main

    response = TestClient(main.app).post("/simulate", json={"power_mw": "large"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"
    assert response.json()["field"] == "power_mw"


def test_post_simulate_rejects_zero_and_negative_power():
    import main

    client = TestClient(main.app)
    for power_mw in (0, -1):
        response = client.post("/simulate", json=simulation_payload(power_mw=power_mw))
        assert response.status_code == 422
        assert response.json()["field"] == "power_mw"


def test_post_simulate_rejects_invalid_efficiency():
    import main

    client = TestClient(main.app)
    for efficiency in (0, 1.01):
        response = client.post(
            "/simulate",
            json=simulation_payload(round_trip_efficiency=efficiency),
        )
        assert response.status_code == 422
        assert response.json()["field"] == "round_trip_efficiency"


def test_post_simulate_supports_multiple_cycles(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )

    response = TestClient(main.app).post(
        "/simulate", json=simulation_payload(cycles=2)
    )

    assert response.status_code == 200
    assert response.json()["discharged_energy_mwh"] == 80
    assert response.json()["estimated_net_margin"] == 5140


def test_post_simulate_maps_caiso_failure_to_structured_error(monkeypatch):
    import main

    def fail(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", fail)
    response = TestClient(main.app).post("/simulate", json=simulation_payload())

    assert response.status_code == 502
    assert response.json()["upstream_service"] == "CAISO OASIS"


def test_post_simulate_maps_caiso_429_to_structured_upstream_error(monkeypatch):
    import main

    def fail(location, market, date):
        raise main.CaisoOasisError(
            "CAISO OASIS request failed: 429 Client Error: Too Many Requests"
        )

    monkeypatch.setattr(main, "fetch_lmp_data", fail)
    response = TestClient(main.app).post("/simulate", json=simulation_payload())

    assert response.status_code == 502
    assert response.json() == {
        "error_code": "upstream_service_error",
        "message": (
            "CAISO OASIS request failed: "
            "429 Client Error: Too Many Requests"
        ),
        "upstream_service": "CAISO OASIS",
    }


def test_health_endpoint_returns_service_and_supabase_status(monkeypatch):
    import main

    monkeypatch.setattr(main, "check_supabase_connectivity", lambda: "connected")
    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service_name"] == "PUBBA Power API"
    assert body["api_version"] == "1.0.0"
    assert body["current_utc_timestamp"].endswith(("Z", "+00:00"))
    assert body["supabase_connectivity_status"] == "connected"


def test_health_endpoint_reports_degraded_when_supabase_is_not_configured(
    monkeypatch,
):
    import main

    monkeypatch.setattr(
        main, "check_supabase_connectivity", lambda: "not_configured"
    )

    body = TestClient(main.app).get("/health").json()

    assert body["status"] == "degraded"
    assert body["supabase_connectivity_status"] == "not_configured"


def test_portfolio_summary_endpoint_returns_supabase_metrics(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "build_portfolio_summary",
        lambda **kwargs: {
            "portfolio": {
                "id": "portfolio-1", "code": "ONLY1", "name": "PUBBA Power",
                "default_market": "CAISO",
                "reporting_timezone": "America/Los_Angeles", "currency_code": "USD",
            },
            "period": {
                "start_at": None, "end_at": "2026-07-14T12:00:00Z",
                "timezone": "America/Los_Angeles",
            },
            "financial": {
                "gross_revenue": 10000, "charging_cost": 4000,
                "net_profit": 5000, "total_portfolio_profit": 5000,
                "trading_return": 1.25, "weighted_average_spread_per_mwh": 60,
            },
            "period_revenue": {
                "today": 100, "week": 200, "month": 300,
                "quarter": 400, "year": 500,
            },
            "operations": {
                "total_dispatches": 8, "purchased_energy_mwh": 100,
                "sold_energy_mwh": 80, "energy_throughput_mwh": 180,
                "last_dispatch_at": "2026-07-14T10:00:00Z",
            },
            "fleet": {
                "active_assets": 2, "power_capacity_mw": 20,
                "energy_capacity_mwh": 80,
            },
            "metadata": {
                "metric_version": "1.0", "data_freshness_at": "2026-07-14T10:00:00Z",
                "generated_at": "2026-07-14T12:00:00Z",
            },
        },
    )

    response = TestClient(main.app).get("/portfolio/summary")

    assert response.status_code == 200
    assert response.json()["portfolio"]["code"] == "ONLY1"
    assert response.json()["financial"]["net_profit"] == "5000"


def test_portfolio_assets_endpoint_returns_asset_performance(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "get_asset_performance",
        lambda: [{
            "asset_id": "BAT-001",
            "asset_name": "North Battery",
            "technology": "LFP",
            "status": "Active",
            "power_mw": 10,
            "energy_mwh": 40,
            "location": "NP15",
            "total_dispatches": 2,
            "total_revenue": 2000,
            "total_charging_cost": 650,
            "total_profit": 1150,
            "average_profit_per_dispatch": 575,
            "last_dispatch_time": "2025-07-19T19:00:00Z",
        }],
    )

    response = TestClient(main.app).get("/portfolio/assets")

    assert response.status_code == 200
    assert response.json()[0]["asset_id"] == "BAT-001"
    assert response.json()[0]["average_profit_per_dispatch"] == 575


def test_dashboard_summary_endpoint_forwards_options(monkeypatch):
    import main

    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return {"kpis": {"today_dispatches": 2}, "status": {"api": "connected"}}

    monkeypatch.setattr(main, "build_dashboard_summary", build)
    response = TestClient(main.app).get(
        "/dashboard/summary",
        params={"timezone": "America/Denver", "include_market": "false"},
    )

    assert response.status_code == 200
    assert response.json()["kpis"]["today_dispatches"] == 2
    assert captured == {"timezone_name": "America/Denver", "include_market": False}


def test_portfolio_assets_endpoint_identifies_supabase_timeout(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "get_asset_performance",
        lambda: (_ for _ in ()).throw(
            main.SupabaseError(
                "Supabase timed out",
                error_code="supabase_timeout",
                status_code=504,
            )
        ),
    )

    response = TestClient(main.app).get("/portfolio/assets")

    assert response.status_code == 504
    assert response.json() == {
        "error_code": "supabase_timeout",
        "message": "Supabase timed out",
        "upstream_service": "Supabase",
    }


def test_asset_creation_returns_structured_duplicate_error(monkeypatch):
    import main
    from tests.test_operator_auth import AUTH_HEADERS, configure_auth

    configure_auth(monkeypatch, role="admin")

    monkeypatch.setattr(
        main,
        "create_asset",
        lambda fields: (_ for _ in ()).throw(main.DuplicateAssetError("BAT-001")),
    )

    response = TestClient(main.app).post(
        "/assets", headers=AUTH_HEADERS,
        json={"asset_id": "BAT-001", "asset_name": "Battery"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "error_code": "duplicate_asset",
        "message": "Asset already exists: BAT-001",
        "upstream_service": "Supabase",
    }


def test_asset_management_endpoints_use_supabase_service(monkeypatch):
    import main
    from tests.test_operator_auth import AUTH_HEADERS, configure_auth

    configure_auth(monkeypatch, role="admin")

    monkeypatch.setattr(
        main,
        "list_assets",
        lambda limit, offset: [{"asset_id": "BAT-001", "asset_name": "Battery"}],
    )
    monkeypatch.setattr(
        main,
        "get_asset",
        lambda asset_id: {"asset_id": asset_id, "asset_name": "Battery"},
    )
    monkeypatch.setattr(main, "create_asset", lambda fields: {"id": "asset-uuid", **fields})
    monkeypatch.setattr(
        main,
        "update_asset",
        lambda asset_id, fields: {"asset_id": asset_id, **fields},
    )
    client = TestClient(main.app)

    assert client.get("/assets", headers=AUTH_HEADERS).json()[0]["asset_id"] == "BAT-001"
    assert client.get("/assets/BAT-001", headers=AUTH_HEADERS).status_code == 200
    created = client.post(
        "/assets", headers=AUTH_HEADERS,
        json={"asset_id": "BAT-002", "asset_name": "Second"},
    )
    updated = client.patch(
        "/assets/BAT-002", headers=AUTH_HEADERS, json={"status": "inactive"},
    )

    assert created.status_code == 201
    assert created.json()["id"] == "asset-uuid"
    assert updated.status_code == 200
    assert updated.json()["status"] == "inactive"


def test_asset_get_returns_structured_missing_error(monkeypatch):
    import main

    monkeypatch.setattr(main, "get_asset", lambda asset_id: None)

    response = TestClient(main.app).get("/assets/MISSING")

    assert response.status_code == 404
    assert response.json()["error_code"] == "missing_asset"


def test_dispatch_endpoint_forwards_filters_and_pagination(monkeypatch):
    import main

    captured = {}

    def list_records(**kwargs):
        captured.update(kwargs)
        return [{"dispatch_id": "dispatch:one"}]

    monkeypatch.setattr(main, "list_dispatch_events", list_records)
    response = TestClient(main.app).get(
        "/dispatch-events",
        params={
            "start_date": "2025-07-01",
            "end_date": "2025-07-31",
            "asset_id": "BAT-001",
            "market": "RTM",
            "location": "NP15",
            "status": "completed",
            "limit": 25,
            "offset": 50,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["dispatch_id"] == "dispatch:one"
    assert captured["asset_id"] == "BAT-001"
    assert captured["limit"] == 25
    assert captured["offset"] == 50


def test_dispatch_csv_export_matches_filtered_records(monkeypatch):
    import main

    record = {
        "id": "uuid-1",
        "dispatch_id": "dispatch:one",
        "asset_id": "asset-uuid",
        "simulation_id": "simulation-uuid",
        "dispatch_timestamp": "2025-07-18T01:00:00Z",
        "market": "RTM",
        "location": "NP15",
        "status": "completed",
        "energy_mwh": 40,
        "charging_cost": 750,
        "discharge_revenue": 3600,
        "storage_cost": 280,
        "net_profit": 2570,
    }
    captured = {}

    def list_records(**kwargs):
        captured.update(kwargs)
        return [record]

    monkeypatch.setattr(main, "list_dispatch_events", list_records)
    response = TestClient(main.app).get(
        "/dispatch-events/export.csv",
        params={"market": "RTM", "start_date": "2025-07-18"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(response.text)))
    assert rows[0]["dispatch_id"] == "dispatch:one"
    assert rows[0]["net_profit"] == "2570"
    assert captured["market"] == "RTM"
    assert captured["limit"] is None


def test_report_endpoint_returns_supabase_dispatch_aggregation(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "aggregate_report",
        lambda period, **kwargs: [{
            "period_start": "2025-07-01",
            "period_end": "2025-07-31",
            "total_dispatches": 2,
            "total_energy_mwh": 80,
            "charging_cost": 1500,
            "discharge_revenue": 7200,
            "storage_cost": 560,
            "net_profit": 5140,
        }],
    )

    response = TestClient(main.app).get("/reports/monthly")

    assert response.status_code == 200
    assert response.json()[0]["period_start"] == "2025-07-01"
    assert response.json()[0]["net_profit"] == 5140


def test_cors_allows_only_configured_origins(monkeypatch):
    import main

    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://pubba.retool.com, https://app.pubbapower.com",
    )
    client = TestClient(main.create_app())
    allowed = client.options(
        "/simulate",
        headers={
            "Origin": "https://pubba.retool.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        "/simulate",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://pubba.retool.com"
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    assert "access-control-allow-origin" not in denied.headers


def test_cors_parses_pubba_and_retool_origins_with_whitespace(monkeypatch):
    import main

    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        " , https://pubbapower.com,  https://www.pubbapower.com , "
        "https://app.pubbapower.com, ,https://pubba.retool.com, ",
    )

    assert main._allowed_origins() == [
        "https://pubbapower.com",
        "https://www.pubbapower.com",
        "https://app.pubbapower.com",
        "https://pubba.retool.com",
    ]
    client = TestClient(main.create_app())
    for origin in main._allowed_origins():
        response = client.options(
            "/simulate",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_cors_does_not_default_to_wildcard(monkeypatch):
    import main

    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    response = TestClient(main.create_app()).get(
        "/health", headers={"Origin": "https://example.com"}
    )

    assert "access-control-allow-origin" not in response.headers


def test_existing_root_and_get_simulate_endpoints_still_work(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    client = TestClient(main.app)

    assert client.get("/").status_code == 200
    assert client.get(
        "/simulate", params={"power_mw": 10, "duration_hours": 4}
    ).status_code == 200
