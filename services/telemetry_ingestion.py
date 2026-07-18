"""Secure, provider-neutral single and partial-success batch ingestion."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from services.telemetry import TelemetryValidationError, parse_timestamp
from services.telemetry_adapters import GenericJsonTelemetryAdapter, TelemetryAdapter
from supabase import (
    SupabaseError,
    create_telemetry,
    get_latest_telemetry_for_source,
)


logger = logging.getLogger("pubba.telemetry.ingestion")
DEFAULT_MAX_BATCH_SIZE = 100
HARD_MAX_BATCH_SIZE = 1000


def configured_batch_limit() -> int:
    try:
        value = int(os.getenv("TELEMETRY_MAX_BATCH_SIZE", str(DEFAULT_MAX_BATCH_SIZE)))
    except ValueError as exc:
        raise RuntimeError("TELEMETRY_MAX_BATCH_SIZE must be an integer") from exc
    if not 1 <= value <= HARD_MAX_BATCH_SIZE:
        raise RuntimeError(
            f"TELEMETRY_MAX_BATCH_SIZE must be between 1 and {HARD_MAX_BATCH_SIZE}"
        )
    return value


def _classification_guard(
    record: dict[str, Any], latest_for_source: dict | None,
) -> None:
    if latest_for_source is None:
        return
    if bool(latest_for_source.get("is_simulated")) != record["is_simulated"]:
        raise TelemetryValidationError(
            "telemetry_source cannot mix simulated and operational observations",
            field="is_simulated",
        )
    if (
        str(latest_for_source.get("asset_id") or "") == record["asset_id"]
        and parse_timestamp(record["recorded_at"])
        < parse_timestamp(latest_for_source.get("recorded_at"))
    ):
        raise TelemetryValidationError(
            "recorded_at is older than the latest observation for this asset and source",
            field="recorded_at",
        )


def ingest_batch(
    observations: list[dict[str, Any]], *,
    adapter: TelemetryAdapter | None = None,
    persist: Callable[[dict], dict] = create_telemetry,
    source_latest: Callable[[str], dict | None] = get_latest_telemetry_for_source,
    max_batch_size: int | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    requested_at = datetime.now(timezone.utc)
    limit = max_batch_size or configured_batch_limit()
    if not observations:
        raise TelemetryValidationError("observations must contain at least one record", field="observations")
    if len(observations) > limit:
        raise TelemetryValidationError(
            f"observations exceeds the maximum batch size of {limit}", field="observations"
        )
    selected_adapter = adapter or GenericJsonTelemetryAdapter()
    ingestion_id = str(uuid4())
    accepted, duplicates, rejected = [], [], []
    normalized_count = 0
    source_classes: dict[str, bool] = {}
    seen: set[tuple[str, str]] = set()
    for index, payload in enumerate(observations):
        try:
            normalized = selected_adapter.normalize(payload)
            normalized_count += 1
            identity = (normalized["asset_id"], normalized["recorded_at"])
            if identity in seen:
                duplicates.append({"index": index, "asset_id": identity[0], "recorded_at": identity[1]})
                continue
            seen.add(identity)
            source = normalized["telemetry_source"]
            if source in source_classes and source_classes[source] != normalized["is_simulated"]:
                raise TelemetryValidationError(
                    "telemetry_source cannot mix simulated and operational observations",
                    field="is_simulated",
                )
            source_classes[source] = normalized["is_simulated"]
            _classification_guard(normalized, source_latest(source))
            created = persist(normalized)
            accepted.append({
                "index": index,
                "asset_id": normalized["asset_id"],
                "recorded_at": normalized["recorded_at"],
                "id": created.get("id"),
                "record": {**created, **normalized},
            })
        except SupabaseError as exc:
            if exc.error_code == "duplicate_telemetry":
                duplicates.append({
                    "index": index,
                    "asset_id": str(payload.get("asset_id") or ""),
                    "recorded_at": str(payload.get("recorded_at") or ""),
                })
            elif exc.error_code == "missing_asset":
                rejected.append({"index": index, "code": "unknown_asset", "field": "asset_id", "message": "Asset was not found"})
            else:
                raise
        except TelemetryValidationError as exc:
            rejected.append({
                "index": index, "code": "invalid_telemetry",
                "field": exc.field, "message": str(exc),
            })
    status = (
        "accepted" if len(accepted) == len(observations)
        else "rejected" if len(rejected) == len(observations)
        else "partial"
    )
    audit = {
        "ingestion_id": ingestion_id,
        "requested_at": requested_at.isoformat(),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "telemetry_sources": sorted(source_classes),
        "received": len(observations),
        "normalized": normalized_count,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "duplicate": len(duplicates),
        "status": status,
        "error_summary": sorted({item["code"] for item in rejected}),
        "processing_duration_ms": round((time.monotonic() - started) * 1000, 3),
    }
    logger.info("Telemetry ingestion completed", extra={"telemetry_ingestion": audit})
    return {
        **audit,
        "accepted_records": accepted,
        "rejected_records": rejected,
        "duplicate_records": duplicates,
    }
