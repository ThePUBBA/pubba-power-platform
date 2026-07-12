from datetime import datetime, timedelta, timezone

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


def test_post_simulate_archives_to_airtable_when_configured(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    monkeypatch.setattr(main, "airtable_is_configured", lambda: True)
    archived = {}
    monkeypatch.setattr(
        main,
        "save_simulation_to_airtable",
        lambda result: archived.update(result),
    )

    response = TestClient(main.app).post("/simulate", json=simulation_payload())

    assert response.status_code == 200
    assert archived["location"] == "TH_NP15_GEN-APND"
    assert archived["market"] == "RTM"
    assert archived["date"] == "2025-04-01"
    assert archived["estimated_net_margin"] == 2570


def test_post_simulate_returns_result_when_airtable_is_unavailable(
    monkeypatch, caplog
):
    import main

    monkeypatch.setattr(
        main,
        "fetch_lmp_data",
        lambda location, market, date: make_lmp_frame(
            [100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]
        ),
    )
    monkeypatch.setattr(main, "airtable_is_configured", lambda: True)

    def fail(_result):
        raise main.AirtableError(
            "Airtable record write failed: HTTP status=422; "
            "error_type=UNKNOWN_FIELD_NAME; message=Unknown field name; "
            'response_body={"error":{"type":"UNKNOWN_FIELD_NAME"}}'
        )

    monkeypatch.setattr(main, "save_simulation_to_airtable", fail)

    response = TestClient(main.app).post("/simulate", json=simulation_payload())

    assert response.status_code == 200
    assert response.json()["estimated_net_margin"] == 2570
    assert "Unable to archive simulation in Airtable" in caplog.text
    assert "HTTP status=422" in caplog.text
    assert "error_type=UNKNOWN_FIELD_NAME" in caplog.text
    assert "response_body=" in caplog.text


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


def test_health_endpoint_returns_service_metadata():
    import main

    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service_name"] == "Only1 LMP API"
    assert body["api_version"] == "1.0.0"
    assert body["current_utc_timestamp"].endswith(("Z", "+00:00"))


def test_cors_allows_only_configured_origins(monkeypatch):
    import main

    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://only1.retool.com, https://dashboard.only1power.com",
    )
    client = TestClient(main.create_app())
    allowed = client.options(
        "/simulate",
        headers={
            "Origin": "https://only1.retool.com",
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
    assert allowed.headers["access-control-allow-origin"] == "https://only1.retool.com"
    assert "access-control-allow-origin" not in denied.headers


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
