"""Validation, freshness, readiness, and development telemetry utilities."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


DEFAULT_STALE_AFTER_MINUTES = 15
MAX_FUTURE_SKEW_SECONDS = 60


class TelemetryValidationError(ValueError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def parse_timestamp(value: object, *, field: str = "recorded_at") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise TelemetryValidationError(
                f"{field} must be a valid timezone-aware timestamp", field=field
            ) from exc
    else:
        raise TelemetryValidationError(
            f"{field} must be a valid timezone-aware timestamp", field=field
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TelemetryValidationError(
            f"{field} must include a timezone offset", field=field
        )
    return parsed.astimezone(timezone.utc)


def _optional_number(
    value: object, *, field: str, minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TelemetryValidationError(f"{field} must be numeric", field=field) from exc
    if not number.is_finite():
        raise TelemetryValidationError(f"{field} must be finite", field=field)
    if minimum is not None and number < minimum:
        raise TelemetryValidationError(f"{field} must be at least {minimum}", field=field)
    if maximum is not None and number > maximum:
        raise TelemetryValidationError(f"{field} must be at most {maximum}", field=field)
    return float(number)


def normalize_telemetry(
    record: dict[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    """Validate one observation without converting missing readings to zero."""
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    asset_id = str(record.get("asset_id") or "").strip()
    source = str(record.get("telemetry_source") or "").strip()
    if not asset_id:
        raise TelemetryValidationError("asset_id is required", field="asset_id")
    if not source:
        raise TelemetryValidationError(
            "telemetry_source is required", field="telemetry_source"
        )
    recorded_at = parse_timestamp(record.get("recorded_at"))
    if recorded_at > current_time + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        raise TelemetryValidationError(
            "recorded_at cannot be in the future", field="recorded_at"
        )
    normalized = {
        "asset_id": asset_id,
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "state_of_charge_pct": _optional_number(
            record.get("state_of_charge_pct"), field="state_of_charge_pct",
            minimum=Decimal("0"), maximum=Decimal("100"),
        ),
        "current_power_mw": _optional_number(
            record.get("current_power_mw"), field="current_power_mw"
        ),
        "available_charge_power_mw": _optional_number(
            record.get("available_charge_power_mw"),
            field="available_charge_power_mw", minimum=Decimal("0"),
        ),
        "available_discharge_power_mw": _optional_number(
            record.get("available_discharge_power_mw"),
            field="available_discharge_power_mw", minimum=Decimal("0"),
        ),
        "available_energy_mwh": _optional_number(
            record.get("available_energy_mwh"),
            field="available_energy_mwh", minimum=Decimal("0"),
        ),
        "temperature_c": _optional_number(
            record.get("temperature_c"), field="temperature_c"
        ),
        "operational_status": (
            str(record["operational_status"]).strip().lower()
            if record.get("operational_status") not in (None, "") else None
        ),
        "availability_status": (
            str(record["availability_status"]).strip().lower()
            if record.get("availability_status") not in (None, "") else None
        ),
        "telemetry_source": source,
        "is_simulated": bool(record.get("is_simulated", False)),
    }
    return normalized


def telemetry_freshness(
    recorded_at: object, *, now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> dict[str, Any]:
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        stamp = parse_timestamp(recorded_at)
    except TelemetryValidationError:
        return {"status": "unavailable", "age_seconds": None, "stale": True}
    age = max(0, int((current_time - stamp).total_seconds()))
    stale = age > stale_after_minutes * 60
    return {"status": "stale" if stale else "fresh", "age_seconds": age, "stale": stale}


@dataclass(frozen=True)
class Readiness:
    state: str
    explanation: str

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "explanation": self.explanation}


def calculate_dispatch_readiness(
    telemetry: dict[str, Any] | None, *, now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> Readiness:
    if not telemetry:
        return Readiness("telemetry_unavailable", "Telemetry unavailable")
    freshness = telemetry_freshness(
        telemetry.get("recorded_at"), now=now,
        stale_after_minutes=stale_after_minutes,
    )
    if freshness["stale"]:
        age_minutes = (freshness["age_seconds"] or 0) // 60
        return Readiness(
            "telemetry_stale", f"Telemetry stale — last update was {age_minutes} minutes ago"
        )
    operational = str(telemetry.get("operational_status") or "").lower()
    availability = str(telemetry.get("availability_status") or "").lower()
    blocked = {"maintenance", "fault", "offline", "unavailable", "retired"}
    if operational in blocked or availability in blocked:
        status = operational if operational in blocked else availability
        return Readiness("unavailable", f"Unavailable — asset status is {status}")
    soc = telemetry.get("state_of_charge_pct")
    charge = telemetry.get("available_charge_power_mw")
    discharge = telemetry.get("available_discharge_power_mw")
    if soc is None or (charge is None and discharge is None):
        return Readiness("limited", "Limited — required telemetry is incomplete")
    can_charge = charge is not None and charge > 0 and soc < 100
    can_discharge = discharge is not None and discharge > 0 and soc > 0
    if can_charge and can_discharge:
        return Readiness(
            "ready_charge_discharge",
            f"Ready to charge or discharge — {soc:g}% SOC, {charge:g} MW charge and {discharge:g} MW discharge available",
        )
    if can_discharge:
        return Readiness(
            "ready_to_discharge",
            f"Ready to discharge — {soc:g}% SOC and {discharge:g} MW available",
        )
    if can_charge:
        return Readiness(
            "ready_to_charge",
            f"Ready to charge — {soc:g}% SOC and {charge:g} MW available",
        )
    return Readiness("limited", "Limited — no charging or discharging power is available")


def generate_development_telemetry(
    asset_id: str, *, recorded_at: datetime | None = None, seed: int | None = None,
) -> dict[str, Any]:
    """Generate one explicitly simulated record only when deliberately enabled."""
    if os.getenv("PUBBA_ENABLE_SIMULATED_TELEMETRY", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("Simulated telemetry generation is disabled")
    rng = random.Random(seed)
    soc = round(rng.uniform(30, 85), 1)
    return normalize_telemetry({
        "asset_id": asset_id,
        "recorded_at": recorded_at or datetime.now(timezone.utc),
        "state_of_charge_pct": soc,
        "current_power_mw": round(rng.uniform(-4, 4), 2),
        "available_charge_power_mw": round(rng.uniform(2, 10), 2),
        "available_discharge_power_mw": round(rng.uniform(2, 10), 2),
        "available_energy_mwh": round(soc / 100 * 40, 2),
        "temperature_c": round(rng.uniform(20, 34), 1),
        "operational_status": "normal",
        "availability_status": "available",
        "telemetry_source": "development_generator",
        "is_simulated": True,
    }, now=(recorded_at or datetime.now(timezone.utc)) + timedelta(seconds=1))
