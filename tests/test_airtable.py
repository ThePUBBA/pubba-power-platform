import json

import airtable
import requests


class MockResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self.payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        return self.payload if self.payload is not None else {}


def simulation_result():
    return {
        "location": "TH_NP15_GEN-APND",
        "market": "RTM",
        "date": "2025-07-18",
        "power_mw": 10,
        "duration_hours": 4,
        "round_trip_efficiency": 0.8,
        "cycles": 2,
        "charging_cost": 750,
        "discharge_revenue": 3600,
        "gross_arbitrage_margin": 2850,
        "storage_lease_cost": 200,
        "variable_operating_cost": 80,
        "estimated_net_margin": 2570,
        "charging_window": {
            "start_timestamp": "2025-07-18T01:00:00-07:00",
            "end_timestamp": "2025-07-18T05:00:00-07:00",
        },
        "discharging_window": {
            "start_timestamp": "2025-07-18T16:00:00-07:00",
            "end_timestamp": "2025-07-18T20:00:00-07:00",
        },
    }


def configure_airtable(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "pat_test")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appTestBase")
    monkeypatch.setenv("AIRTABLE_TABLE_NAME", "Simulation Archive")
    monkeypatch.setenv("AIRTABLE_ASSETS_TABLE", "Assets")
    monkeypatch.setenv("AIRTABLE_DISPATCH_EVENTS_TABLE", "Dispatch Events")
    monkeypatch.setenv("AIRTABLE_DAILY_PNL_TABLE", "Daily P&L")


def test_save_simulation_posts_expected_airtable_record(monkeypatch):
    configure_airtable(monkeypatch)
    captured = {}

    def mock_request(method, url, headers, params, json, timeout):
        captured.update(
            method=method,
            url=url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        return MockResponse(payload={"id": "recSimulation", "fields": json["fields"]})

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    record_id = airtable.save_simulation_to_airtable(simulation_result())

    assert captured["url"] == (
        "https://api.airtable.com/v0/appTestBase/Simulation%20Archive"
    )
    assert captured["headers"]["Authorization"] == "Bearer pat_test"
    assert captured["timeout"] == airtable.AIRTABLE_TIMEOUT_SECONDS
    assert set(captured["json"]) == {"fields", "typecast"}
    assert captured["json"]["typecast"] is True
    fields = captured["json"]["fields"]
    assert fields["location"] == "TH_NP15_GEN-APND"
    assert fields["estimated_net_margin"] == 2570
    assert fields["charging_window_start"] == "2025-07-18T01:00:00-07:00"
    assert fields["discharging_window_end"] == "2025-07-18T20:00:00-07:00"
    assert fields["timestamp"].endswith("+00:00")
    assert record_id == "recSimulation"


def test_save_simulation_does_nothing_without_complete_configuration(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)
    monkeypatch.delenv("AIRTABLE_TABLE_NAME", raising=False)
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )

    assert airtable.airtable_is_configured() is False
    airtable.save_simulation_to_airtable(simulation_result())


def test_save_simulation_reports_unknown_airtable_field(monkeypatch):
    configure_airtable(monkeypatch)
    payload = {
        "error": {
            "type": "UNKNOWN_FIELD_NAME",
            "message": 'Unknown field name: "estimated_net_margin"',
        }
    }
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(422, payload),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        message = str(exc)
        assert "HTTP status=422" in message
        assert "error_type=UNKNOWN_FIELD_NAME" in message
        assert 'Unknown field name: "estimated_net_margin"' in message
        assert json.dumps(payload) in message
        assert "pat_test" not in message
    else:
        raise AssertionError("Expected AirtableError")


def test_find_asset_by_asset_id_returns_matching_asset(monkeypatch):
    configure_airtable(monkeypatch)
    captured = {}

    def mock_request(method, url, headers, params, json, timeout):
        captured.update(method=method, url=url, params=params)
        return MockResponse(
            payload={
                "records": [
                    {"id": "recAsset", "fields": {"asset_id": "BAT-001"}}
                ]
            }
        )

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    asset = airtable.find_asset_by_asset_id("BAT-001")

    assert asset["id"] == "recAsset"
    assert captured["method"] == "get"
    assert captured["url"].endswith("/Assets")
    assert captured["params"]["filterByFormula"] == "{asset_id}='BAT-001'"


def test_find_asset_by_asset_id_returns_none_when_missing(monkeypatch):
    configure_airtable(monkeypatch)
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload={"records": []}),
    )

    assert airtable.find_asset_by_asset_id("MISSING") is None


def test_create_dispatch_event_links_asset_and_simulation(monkeypatch):
    configure_airtable(monkeypatch)
    calls = []

    def mock_request(method, url, headers, params, json, timeout):
        calls.append((method, url, params, json))
        if method == "get":
            return MockResponse(payload={"records": []})
        return MockResponse(payload={"id": "recDispatch", "fields": json["fields"]})

    monkeypatch.setattr(airtable.requests, "request", mock_request)
    record = airtable.create_dispatch_event(
        {"id": "recAsset", "fields": {"asset_id": "BAT-001"}},
        simulation_result(),
        "recSimulation",
    )

    assert record["id"] == "recDispatch"
    assert calls[0][2]["filterByFormula"] == (
        "{dispatch_id}='dispatch:recSimulation'"
    )
    fields = calls[1][3]["fields"]
    assert fields["dispatch_id"] == "dispatch:recSimulation"
    assert fields["asset_id"] == ["recAsset"]
    assert fields["simulation"] == ["recSimulation"]


def test_create_dispatch_event_reuses_existing_record_on_retry(monkeypatch):
    configure_airtable(monkeypatch)
    calls = []

    def mock_request(method, url, headers, params, json, timeout):
        calls.append(method)
        return MockResponse(
            payload={
                "records": [
                    {
                        "id": "recDispatch",
                        "fields": {"dispatch_id": "dispatch:recSimulation"},
                    }
                ]
            }
        )

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    record = airtable.create_dispatch_event(
        {"id": "recAsset", "fields": {"asset_id": "BAT-001"}},
        simulation_result(),
        "recSimulation",
    )

    assert record["id"] == "recDispatch"
    assert calls == ["get"]


def test_recalculate_daily_pnl_creates_totals_from_dispatch_ledger(monkeypatch):
    configure_airtable(monkeypatch)
    responses = iter(
        [
            {"records": [{"fields": {
                "discharge_revenue": "3600",
                "charging_cost": "750",
                "estimated_profit": "2570",
            }}]},
            {"records": []},
            {"id": "recDaily", "fields": {}},
        ]
    )
    calls = []

    def mock_request(method, url, headers, params, json, timeout):
        calls.append((method, json))
        return MockResponse(payload=next(responses))

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    record = airtable.recalculate_daily_pnl("2025-07-18")

    assert record["id"] == "recDaily"
    assert [call[0] for call in calls] == ["get", "get", "post"]
    assert calls[2][1]["fields"] == {
        "date": "2025-07-18",
        "gross_revenue": 3600.0,
        "charging_cost": 750.0,
        "storage_cost": 280.0,
        "net_profit": 2570.0,
    }


def test_recalculate_daily_pnl_retry_does_not_double_count(monkeypatch):
    configure_airtable(monkeypatch)
    payloads = []

    def mock_request(method, url, headers, params, json, timeout):
        if "Dispatch%20Events" in url:
            return MockResponse(payload={"records": [{"fields": {
                "discharge_revenue": "3600",
                "charging_cost": "750",
                "estimated_profit": "2570",
            }}]})
        if method == "get":
            return MockResponse(payload={"records": [{
                "id": "recDaily",
                "fields": {"net_profit": "2570"},
            }]})
        payloads.append(json["fields"])
        return MockResponse(payload={"id": "recDaily", "fields": json["fields"]})

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    airtable.recalculate_daily_pnl("2025-07-18")
    airtable.recalculate_daily_pnl("2025-07-18")

    assert len(payloads) == 2
    assert payloads[0] == payloads[1]
    assert payloads[1]["net_profit"] == 2570.0


def test_recalculate_daily_pnl_detects_duplicate_rows(monkeypatch):
    configure_airtable(monkeypatch)
    responses = iter(
        [
            {"records": []},
            {"records": [{"id": "recOne"}, {"id": "recTwo"}]},
        ]
    )
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload=next(responses)),
    )

    try:
        airtable.recalculate_daily_pnl("2025-07-18")
    except airtable.AirtableIntegrityError as exc:
        assert "Duplicate Daily P&L rows" in str(exc)
    else:
        raise AssertionError("Expected AirtableIntegrityError")


def test_get_portfolio_summary_aggregates_tables(monkeypatch):
    configure_airtable(monkeypatch)
    responses = iter(
        [
            {"records": [
                {"fields": {"status": "Active"}},
                {"fields": {"status": "inactive"}},
            ]},
            {"records": [{"fields": {}}, {"fields": {}}]},
            {"records": [{"fields": {}}]},
            {"records": [
                {"fields": {
                    "gross_revenue": "1000",
                    "charging_cost": "400",
                    "storage_cost": "100",
                    "net_profit": "500",
                }},
                {"fields": {
                    "gross_revenue": "200",
                    "charging_cost": "50",
                    "storage_cost": "25",
                    "net_profit": "125",
                }},
            ]},
        ]
    )
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload=next(responses)),
    )

    summary = airtable.get_portfolio_summary()

    assert summary == {
        "total_assets": 2,
        "active_assets": 1,
        "total_simulations": 2,
        "total_dispatches": 1,
        "cumulative_revenue": 1200.0,
        "cumulative_charging_cost": 450.0,
        "cumulative_storage_cost": 125.0,
        "cumulative_net_profit": 625.0,
    }


def test_get_portfolio_summary_handles_empty_tables(monkeypatch):
    configure_airtable(monkeypatch)
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload={"records": []}),
    )

    assert airtable.get_portfolio_summary() == {
        "total_assets": 0,
        "active_assets": 0,
        "total_simulations": 0,
        "total_dispatches": 0,
        "cumulative_revenue": 0,
        "cumulative_charging_cost": 0,
        "cumulative_storage_cost": 0,
        "cumulative_net_profit": 0,
    }


def test_list_records_follows_airtable_pagination(monkeypatch):
    configure_airtable(monkeypatch)
    calls = []

    def mock_request(method, url, headers, params, json, timeout):
        calls.append(dict(params))
        if len(calls) == 1:
            return MockResponse(
                payload={"records": [{"id": "recOne"}], "offset": "next-page"}
            )
        return MockResponse(payload={"records": [{"id": "recTwo"}]})

    monkeypatch.setattr(airtable.requests, "request", mock_request)

    records = airtable._list_records("Assets")

    assert [record["id"] for record in records] == ["recOne", "recTwo"]
    assert calls[1]["offset"] == "next-page"


def test_get_portfolio_summary_rejects_malformed_numeric_values(monkeypatch):
    configure_airtable(monkeypatch)
    responses = iter(
        [
            {"records": []},
            {"records": []},
            {"records": []},
            {"records": [{"fields": {"net_profit": "not-a-number"}}]},
        ]
    )
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(payload=next(responses)),
    )

    try:
        airtable.get_portfolio_summary()
    except airtable.AirtableError as exc:
        assert "invalid value" in str(exc)
    else:
        raise AssertionError("Expected AirtableError")


def test_get_portfolio_summary_propagates_airtable_timeout(monkeypatch):
    configure_airtable(monkeypatch)
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.Timeout("Airtable timed out")
        ),
    )

    try:
        airtable.get_portfolio_summary()
    except airtable.AirtableError as exc:
        assert "error_type=request_error" in str(exc)
    else:
        raise AssertionError("Expected AirtableError")


def test_save_simulation_reports_airtable_403_without_exposing_token(monkeypatch):
    configure_airtable(monkeypatch)
    payload = {
        "error": {
            "type": "AUTHENTICATION_REQUIRED",
            "message": "Invalid permissions, or the requested model was not found",
        }
    }
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(403, payload),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        message = str(exc)
        assert "HTTP status=403" in message
        assert "error_type=AUTHENTICATION_REQUIRED" in message
        assert "Invalid permissions" in message
        assert json.dumps(payload) in message
        assert "pat_test" not in message
    else:
        raise AssertionError("Expected AirtableError")


def test_save_simulation_reports_invalid_airtable_field_type(monkeypatch):
    configure_airtable(monkeypatch)
    payload = {
        "error": {
            "type": "INVALID_VALUE_FOR_COLUMN",
            "message": 'Field "power_mw" cannot accept the provided value',
        }
    }
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(422, payload),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        message = str(exc)
        assert "HTTP status=422" in message
        assert "error_type=INVALID_VALUE_FOR_COLUMN" in message
        assert 'Field "power_mw" cannot accept the provided value' in message
        assert "response_body=" in message
        assert "pat_test" not in message
    else:
        raise AssertionError("Expected AirtableError")


def test_airtable_error_redacts_token_from_response(monkeypatch):
    configure_airtable(monkeypatch)
    payload = {
        "error": {
            "type": "INVALID_REQUEST",
            "message": "Rejected token pat_test",
        }
    }
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: MockResponse(422, payload),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        assert "pat_test" not in str(exc)
        assert "[REDACTED]" in str(exc)
    else:
        raise AssertionError("Expected AirtableError")


def test_save_simulation_reports_airtable_timeout_without_exposing_token(monkeypatch):
    configure_airtable(monkeypatch)
    monkeypatch.setattr(
        airtable.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.Timeout("request using pat_test timed out")
        ),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        message = str(exc)
        assert "HTTP status=unavailable" in message
        assert "error_type=request_error" in message
        assert "timed out" in message
        assert "pat_test" not in message
        assert "[REDACTED]" in message
    else:
        raise AssertionError("Expected AirtableError")
