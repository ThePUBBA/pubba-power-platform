"""Provider-neutral telemetry adapter contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from services.telemetry import TelemetryValidationError, normalize_telemetry


class TelemetryAdapter(ABC):
    source_name: str

    @abstractmethod
    def validate_source_payload(self, payload: dict[str, Any]) -> None:
        """Validate source-specific shape without persistence side effects."""

    @abstractmethod
    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Map one source payload into the normalized telemetry schema."""

    @abstractmethod
    def health_check(self) -> dict[str, str]:
        """Describe adapter capability, not live source connectivity."""


class GenericJsonTelemetryAdapter(TelemetryAdapter):
    """Adapter for provider-neutral JSON; this is not a vendor integration."""

    source_name = "generic_json"

    def validate_source_payload(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise TelemetryValidationError("Telemetry observation must be an object")
        for field in ("asset_id", "recorded_at", "telemetry_source", "is_simulated"):
            if field not in payload:
                raise TelemetryValidationError(f"{field} is required", field=field)
        if not isinstance(payload["is_simulated"], bool):
            raise TelemetryValidationError(
                "is_simulated must be explicitly true or false", field="is_simulated"
            )

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.validate_source_payload(payload)
        return normalize_telemetry(payload)

    def health_check(self) -> dict[str, str]:
        return {
            "adapter": self.source_name,
            "status": "ready",
            "connectivity": "not_applicable",
        }
