from datetime import datetime, timedelta, timezone

import pytest

from services.telemetry import TelemetryValidationError, source_health
from services.telemetry_ingestion import ingest_batch
from services.telemetry_sources import (
    AssetIdentityMap,
    AssetIdentityMapping,
    SourceRuntimeRegistry,
    merge_source_runtime_health,
    sanitize_source_error,
)


NOW = datetime(2026, 7, 18, 3, tzinfo=timezone.utc)


def observation(**updates):
    value = {
        "asset_id": "PUBBA-A01",
        "recorded_at": "2026-07-18T02:59:00Z",
        "state_of_charge_pct": 50,
        "current_power_mw": -1.5,
        "telemetry_source": "documented_source",
        "is_simulated": False,
    }
    value.update(updates)
    return value


def test_asset_identity_mapping_requires_exact_source_site_and_asset():
    identities = AssetIdentityMap([AssetIdentityMapping(
        source_name="documented_source", vendor_site_id="SITE-1",
        vendor_asset_id="EXT-7", asset_id="PUBBA-A01", portfolio_id="portfolio-1",
    )])
    mapping = identities.resolve(
        source_name="documented_source", vendor_site_id="SITE-1",
        vendor_asset_id="EXT-7",
    )
    assert mapping.asset_id == "PUBBA-A01"
    assert mapping.portfolio_id == "portfolio-1"
    with pytest.raises(TelemetryValidationError, match="not mapped"):
        identities.resolve(
            source_name="documented_source", vendor_site_id="SITE-1",
            vendor_asset_id="UNKNOWN",
        )


def test_asset_identity_mapping_loads_from_environment(monkeypatch):
    monkeypatch.setenv(
        "TELEMETRY_ASSET_MAPPINGS_JSON",
        '[{"source_name":"source","vendor_asset_id":"asset","vendor_site_id":"site",'
        '"asset_id":"PUBBA-A01","portfolio_id":"portfolio-1"}]',
    )
    assert AssetIdentityMap.from_environment().resolve(
        source_name="source", vendor_site_id="site", vendor_asset_id="asset"
    ).asset_id == "PUBBA-A01"
    monkeypatch.setenv("TELEMETRY_ASSET_MAPPINGS_JSON", "not-json")
    with pytest.raises(RuntimeError, match="JSON array"):
        AssetIdentityMap.from_environment()


def test_ingestion_rejects_out_of_order_source_observation():
    result = ingest_batch(
        [observation(recorded_at="2026-07-18T02:58:00Z")],
        persist=lambda record: record,
        source_latest=lambda source: observation(recorded_at="2026-07-18T02:59:00Z"),
    )
    assert result["rejected"] == 1
    assert result["rejected_records"][0]["field"] == "recorded_at"


def test_ingestion_audit_has_cycle_traceability_without_raw_payload():
    result = ingest_batch(
        [observation()], persist=lambda record: record,
        source_latest=lambda source: None,
    )
    assert result["normalized"] == 1
    assert result["processing_duration_ms"] >= 0
    assert result["requested_at"].endswith("+00:00")
    assert "authorization" not in str(result).lower()


def test_source_runtime_health_uses_real_connection_and_sanitized_errors():
    registry = SourceRuntimeRegistry()
    registry.record_connection("documented_source", at=NOW)
    connected = merge_source_runtime_health([], registry.snapshot())
    assert connected[0]["status"] == "connected"
    assert connected[0]["last_received_at"] is None

    registry.record_error("documented_source", TimeoutError("secret response body"))
    errored = merge_source_runtime_health([], registry.snapshot())
    assert errored[0]["status"] == "error"
    assert errored[0]["last_error"] == "TimeoutError"
    assert "secret" not in str(errored)
    assert sanitize_source_error(RuntimeError("token=private")) == "RuntimeError"


def test_source_health_distinguishes_delayed_and_stale():
    delayed = source_health(
        [observation(recorded_at=(NOW - timedelta(minutes=10)).isoformat())], now=NOW,
    )
    stale = source_health(
        [observation(recorded_at=(NOW - timedelta(minutes=30)).isoformat())], now=NOW,
    )
    assert delayed[0]["status"] == "delayed"
    assert stale[0]["status"] == "stale"
