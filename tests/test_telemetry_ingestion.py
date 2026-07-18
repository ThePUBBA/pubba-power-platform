from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main
from dashboard.charts import telemetry_history_figure
from dashboard.pages.overview import _selected_asset_id
from services.telemetry import (
    TelemetryFreshnessConfig,
    TelemetryValidationError,
    source_health,
    telemetry_freshness,
)
from services.telemetry_adapters import GenericJsonTelemetryAdapter
from services.telemetry_ingestion import configured_batch_limit, ingest_batch
from supabase import MissingAssetError, SupabaseError


NOW = datetime(2026, 7, 18, 3, tzinfo=timezone.utc)


def observation(**updates):
    value = {
        "asset_id": "FICTIONAL-BAT-001",
        "recorded_at": "2026-07-18T02:59:00Z",
        "state_of_charge_pct": 62,
        "current_power_mw": -2.5,
        "available_charge_power_mw": 7,
        "available_discharge_power_mw": 8,
        "available_energy_mwh": 24.8,
        "temperature_c": 26,
        "operational_status": "normal",
        "availability_status": "available",
        "telemetry_source": "fictional_scada",
        "is_simulated": False,
    }
    value.update(updates)
    return value


def test_generic_json_adapter_requires_explicit_classification_and_preserves_sign():
    adapter = GenericJsonTelemetryAdapter()
    result = adapter.normalize(observation())
    assert result["current_power_mw"] == -2.5
    assert result["is_simulated"] is False
    invalid = observation()
    invalid.pop("is_simulated")
    with pytest.raises(TelemetryValidationError, match="is_simulated is required"):
        adapter.normalize(invalid)
    assert adapter.health_check()["connectivity"] == "not_applicable"


def test_ingestion_accepts_valid_records_and_logs_audit(caplog):
    caplog.set_level("INFO", logger="pubba.telemetry.ingestion")
    result = ingest_batch(
        [observation()], persist=lambda record: {"id": "row", **record},
        source_latest=lambda source: None,
    )
    assert result["status"] == "accepted"
    assert result["accepted"] == 1
    assert result["telemetry_sources"] == ["fictional_scada"]
    assert "Telemetry ingestion completed" in caplog.text


def test_ingestion_reports_partial_success_unknown_asset_and_invalid_soc():
    def persist(record):
        if record["asset_id"] == "UNKNOWN":
            raise MissingAssetError("UNKNOWN")
        return {"id": "created", **record}

    result = ingest_batch(
        [observation(), observation(asset_id="UNKNOWN", recorded_at="2026-07-18T02:58:00Z"),
         observation(state_of_charge_pct=101, recorded_at="2026-07-18T02:57:00Z")],
        persist=persist, source_latest=lambda source: None,
    )
    assert result["status"] == "partial"
    assert (result["accepted"], result["rejected"]) == (1, 2)
    assert {item["code"] for item in result["rejected_records"]} == {
        "unknown_asset", "invalid_telemetry",
    }


def test_ingestion_is_idempotent_for_batch_and_database_duplicates():
    duplicate_error = SupabaseError(
        "duplicate", error_code="duplicate_telemetry", status_code=409
    )
    calls = 0
    def persist(record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise duplicate_error
        return {"id": "row", **record}
    first = observation()
    result = ingest_batch(
        [first, dict(first), observation(recorded_at="2026-07-18T02:58:00Z")],
        persist=persist, source_latest=lambda source: None,
    )
    assert result["duplicate"] == 2
    assert result["accepted"] == 1


def test_ingestion_rejects_source_classification_mixing():
    result = ingest_batch(
        [observation(is_simulated=True)], persist=lambda record: record,
        source_latest=lambda source: observation(is_simulated=False),
    )
    assert result["rejected"] == 1
    assert "cannot mix" in result["rejected_records"][0]["message"]


def test_batch_limit_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("TELEMETRY_MAX_BATCH_SIZE", "2")
    assert configured_batch_limit() == 2
    with pytest.raises(TelemetryValidationError, match="maximum batch size"):
        ingest_batch(
            [observation(recorded_at=f"2026-07-18T02:5{i}:00Z") for i in range(3)],
            persist=lambda record: record, source_latest=lambda source: None,
        )
    monkeypatch.setenv("TELEMETRY_MAX_BATCH_SIZE", "1001")
    with pytest.raises(RuntimeError):
        configured_batch_limit()


def test_freshness_states_use_central_thresholds():
    config = TelemetryFreshnessConfig(60, 120, 300)
    assert telemetry_freshness(NOW - timedelta(seconds=30), now=NOW, config=config)["status"] == "fresh"
    assert telemetry_freshness(NOW - timedelta(seconds=90), now=NOW, config=config)["status"] == "delayed"
    assert telemetry_freshness(NOW - timedelta(seconds=180), now=NOW, config=config)["status"] == "stale"
    assert telemetry_freshness(NOW - timedelta(seconds=400), now=NOW, config=config)["status"] == "offline"


def test_source_health_uses_actual_receipts_not_configuration():
    rows = source_health(
        [observation(recorded_at=(NOW - timedelta(seconds=30)).isoformat())],
        now=NOW, configured_sources=["fictional_scada", "future_bms"],
    )
    health = {row["telemetry_source"]: row["status"] for row in rows}
    assert health == {"fictional_scada": "receiving_data", "future_bms": "never_received"}


def test_batch_endpoint_authorization_partial_success_and_limit(monkeypatch):
    monkeypatch.setenv("TELEMETRY_WRITES_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_WRITE_TOKEN", "secret")
    monkeypatch.setenv("TELEMETRY_MAX_BATCH_SIZE", "2")
    monkeypatch.setattr(main, "get_latest_telemetry_for_source", lambda source: None)
    monkeypatch.setattr(main, "create_telemetry", lambda record: {"id": "row", **record})
    client = TestClient(main.app)
    assert client.post("/telemetry/batch", json={"observations": [observation()]}).status_code == 403
    accepted = client.post(
        "/telemetry/batch", json={"observations": [observation()]},
        headers={"X-Telemetry-Key": "secret"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] == 1
    oversized = client.post(
        "/telemetry/batch",
        json={"observations": [observation(recorded_at=f"2026-07-18T02:5{i}:00Z") for i in range(3)]},
        headers={"X-Telemetry-Key": "secret"},
    )
    assert oversized.status_code == 422


def test_asset_selection_falls_back_safely():
    assets = [{"asset_id": "A"}, {"asset_id": "B"}]
    assert _selected_asset_id(assets, "B") == "B"
    assert _selected_asset_id(assets, "MISSING") == "A"
    assert _selected_asset_id([]) is None


def test_history_chart_includes_availability_and_breaks_large_gaps(monkeypatch):
    monkeypatch.setenv("TELEMETRY_CHART_GAP_SECONDS", "300")
    figure = telemetry_history_figure([
        observation(recorded_at="2026-07-18T01:00:00Z"),
        observation(recorded_at="2026-07-18T02:00:00Z"),
    ])
    assert [trace.name for trace in figure.data] == [
        "State of charge", "Current power", "Charge availability", "Discharge availability",
    ]
    assert None in list(figure.data[0].y)
