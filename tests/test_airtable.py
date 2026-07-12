import json

import airtable


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


def test_save_simulation_posts_expected_airtable_record(monkeypatch):
    configure_airtable(monkeypatch)
    captured = {}

    def mock_post(url, headers, json, timeout):
        captured.update(
            url=url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        return MockResponse()

    monkeypatch.setattr(airtable.requests, "post", mock_post)

    airtable.save_simulation_to_airtable(simulation_result())

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


def test_save_simulation_does_nothing_without_complete_configuration(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)
    monkeypatch.delenv("AIRTABLE_TABLE_NAME", raising=False)
    monkeypatch.setattr(
        airtable.requests,
        "post",
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
        "post",
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
        "post",
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
        "post",
        lambda *args, **kwargs: MockResponse(422, payload),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        assert "pat_test" not in str(exc)
        assert "[REDACTED]" in str(exc)
    else:
        raise AssertionError("Expected AirtableError")
