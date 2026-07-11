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
    assert response.json() == {"detail": "date must use ISO format YYYY-MM-DD"}


def test_lmp_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/lmp")

    assert response.status_code == 502
    assert response.json() == {"detail": "CAISO OASIS request timed out"}


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
    assert "round_trip_efficiency" in response.json()["detail"]


def test_arbitrage_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/arbitrage")

    assert response.status_code == 502
    assert response.json() == {"detail": "CAISO OASIS request timed out"}


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

    assert response.status_code == 400
    assert response.json() == {"detail": "power_mw must be positive"}


def test_simulate_endpoint_maps_caiso_errors_to_502(monkeypatch):
    import main

    def mock_fetch_lmp_data(location, market, date):
        raise main.CaisoOasisError("CAISO OASIS request timed out")

    monkeypatch.setattr(main, "fetch_lmp_data", mock_fetch_lmp_data)
    client = TestClient(main.app)

    response = client.get("/simulate", params={"power_mw": 10})

    assert response.status_code == 502
    assert response.json() == {"detail": "CAISO OASIS request timed out"}
