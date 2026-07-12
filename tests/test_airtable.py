import requests

import airtable


class MockResponse:
    def __init__(self, error=None):
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


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


def test_save_simulation_wraps_airtable_request_errors(monkeypatch):
    configure_airtable(monkeypatch)
    monkeypatch.setattr(
        airtable.requests,
        "post",
        lambda *args, **kwargs: MockResponse(requests.HTTPError("503 unavailable")),
    )

    try:
        airtable.save_simulation_to_airtable(simulation_result())
    except airtable.AirtableError as exc:
        assert "503 unavailable" in str(exc)
    else:
        raise AssertionError("Expected AirtableError")
