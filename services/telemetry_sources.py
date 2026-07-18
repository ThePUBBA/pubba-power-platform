"""Integration-ready contracts for real telemetry sources and asset identity."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from services.telemetry import TelemetryValidationError


@dataclass(frozen=True)
class AssetIdentityMapping:
    """Explicit external-to-PUBBA asset identity; names are never identifiers."""

    source_name: str
    vendor_asset_id: str
    vendor_site_id: str
    asset_id: str
    portfolio_id: str


class AssetIdentityMap:
    def __init__(self, mappings: list[AssetIdentityMapping]) -> None:
        self._mappings: dict[tuple[str, str, str], AssetIdentityMapping] = {}
        for mapping in mappings:
            key = (
                mapping.source_name.strip(), mapping.vendor_site_id.strip(),
                mapping.vendor_asset_id.strip(),
            )
            if not all(key) or not mapping.asset_id.strip() or not mapping.portfolio_id.strip():
                raise ValueError("Telemetry asset mappings require every identity field")
            if key in self._mappings:
                raise ValueError("Duplicate telemetry external asset mapping")
            self._mappings[key] = mapping

    @classmethod
    def from_environment(cls) -> "AssetIdentityMap":
        raw = os.getenv("TELEMETRY_ASSET_MAPPINGS_JSON", "").strip()
        if not raw:
            return cls([])
        try:
            values = json.loads(raw)
            if not isinstance(values, list):
                raise ValueError
            mappings = [AssetIdentityMapping(**value) for value in values]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "TELEMETRY_ASSET_MAPPINGS_JSON must be a JSON array of asset mappings"
            ) from exc
        return cls(mappings)

    def resolve(
        self, *, source_name: str, vendor_site_id: str, vendor_asset_id: str,
    ) -> AssetIdentityMapping:
        key = (source_name.strip(), vendor_site_id.strip(), vendor_asset_id.strip())
        mapping = self._mappings.get(key)
        if mapping is None:
            raise TelemetryValidationError(
                "External asset identity is not mapped for this source",
                field="vendor_asset_id",
            )
        return mapping


class TelemetrySourceConnector(ABC):
    """Transport contract to implement only after a real source is documented."""

    source_name: str

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Test real authentication/connectivity without disclosing credentials."""

    @abstractmethod
    def receive(self) -> list[dict[str, Any]]:
        """Receive one source cycle using its documented polling/push/file model."""


def sanitize_source_error(error: object) -> str:
    """Return a bounded error category without credentials or response bodies."""
    name = type(error).__name__ if isinstance(error, BaseException) else str(error)
    safe = "".join(character for character in name if character.isalnum() or character in "_-")
    return (safe or "SourceError")[:80]


class SourceRuntimeRegistry:
    """Process-local connection state; telemetry receipt remains database-derived."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._states: dict[str, dict[str, Any]] = {}

    def record_connection(self, source_name: str, *, at: datetime | None = None) -> None:
        stamp = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._lock:
            state = self._states.setdefault(source_name, {})
            state.update({"last_successful_connection_at": stamp, "last_error": None})

    def record_error(self, source_name: str, error: object) -> None:
        with self._lock:
            state = self._states.setdefault(source_name, {})
            state["last_error"] = sanitize_source_error(error)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {source: dict(state) for source, state in self._states.items()}


def merge_source_runtime_health(
    health: list[dict[str, Any]], runtime: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add connection diagnostics without claiming telemetry is being received."""
    rows = {str(item["telemetry_source"]): dict(item) for item in health}
    for source, state in runtime.items():
        row = rows.setdefault(source, {
            "telemetry_source": source, "status": "never_received",
            "last_received_at": None, "age_seconds": None,
        })
        row.update(state)
        if state.get("last_error") and row["status"] in {"never_received", "connected"}:
            row["status"] = "error"
        elif state.get("last_successful_connection_at") and row["status"] == "never_received":
            row["status"] = "connected"
    for row in rows.values():
        row.setdefault("last_successful_connection_at", None)
        row.setdefault("last_error", None)
    return [rows[source] for source in sorted(rows)]


source_runtime_registry = SourceRuntimeRegistry()
