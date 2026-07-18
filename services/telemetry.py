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


@dataclass(frozen=True)
class TelemetryFreshnessConfig:
    fresh_seconds: int = 300
    delayed_seconds: int = 900
    stale_seconds: int = 3600

    @classmethod
    def from_environment(cls) -> "TelemetryFreshnessConfig":
        values = {
            "fresh_seconds": int(os.getenv("TELEMETRY_FRESH_SECONDS", "300")),
            "delayed_seconds": int(os.getenv("TELEMETRY_DELAYED_SECONDS", "900")),
            "stale_seconds": int(os.getenv("TELEMETRY_STALE_SECONDS", "3600")),
        }
        if not 0 < values["fresh_seconds"] <= values["delayed_seconds"] <= values["stale_seconds"]:
            raise RuntimeError("Telemetry freshness thresholds must be positive and ordered")
        return cls(**values)


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
    stale_after_minutes: int | None = None,
    config: TelemetryFreshnessConfig | None = None,
) -> dict[str, Any]:
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        stamp = parse_timestamp(recorded_at)
    except TelemetryValidationError:
        return {"status": "unavailable", "age_seconds": None, "stale": True}
    age = max(0, int((current_time - stamp).total_seconds()))
    thresholds = config or TelemetryFreshnessConfig.from_environment()
    if stale_after_minutes is not None:
        thresholds = TelemetryFreshnessConfig(
            fresh_seconds=min(thresholds.fresh_seconds, stale_after_minutes * 60),
            delayed_seconds=stale_after_minutes * 60,
            stale_seconds=max(thresholds.stale_seconds, stale_after_minutes * 60),
        )
    if age <= thresholds.fresh_seconds:
        status = "fresh"
    elif age <= thresholds.delayed_seconds:
        status = "delayed"
    elif age <= thresholds.stale_seconds:
        status = "stale"
    else:
        status = "offline"
    return {"status": status, "age_seconds": age, "stale": status in {"stale", "offline"}}


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


def telemetry_alerts(
    records: list[dict[str, Any]], *, now: datetime | None = None,
    invalid_received: int = 0,
) -> list[dict[str, str]]:
    alerts = []
    for record in records:
        freshness = telemetry_freshness(record.get("recorded_at"), now=now)
        if freshness["status"] in {"stale", "offline"}:
            alerts.append({
                "code": "asset_reporting_stopped" if freshness["status"] == "offline" else "telemetry_stale",
                "severity": "warning",
                "asset_id": str(record.get("asset_id") or "unknown"),
                "message": (
                    "Asset reporting stopped" if freshness["status"] == "offline"
                    else "Telemetry is stale"
                ),
            })
    if invalid_received:
        alerts.append({
            "code": "invalid_telemetry_received", "severity": "warning",
            "asset_id": "portfolio",
            "message": f"{invalid_received} invalid telemetry observation(s) were rejected",
        })
    return alerts


def source_health(
    records: list[dict[str, Any]], *, now: datetime | None = None,
    configured_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        source = str(record.get("telemetry_source") or "").strip()
        if not source:
            continue
        current = latest.get(source)
        try:
            stamp = parse_timestamp(record.get("created_at") or record.get("recorded_at"))
            current_stamp = parse_timestamp(
                current.get("created_at") or current.get("recorded_at")
            ) if current else None
        except TelemetryValidationError:
            latest[source] = {**record, "_invalid": True}
            continue
        if current is None or current_stamp is None or stamp > current_stamp:
            latest[source] = record
    sources = sorted(set(configured_sources or []) | set(latest))
    result = []
    for source in sources:
        record = latest.get(source)
        if not record:
            state, last_received, age = "never_received", None, None
        elif record.get("_invalid"):
            state, last_received, age = "error", record.get("created_at") or record.get("recorded_at"), None
        else:
            receipt = record.get("created_at") or record.get("recorded_at")
            freshness = telemetry_freshness(receipt, now=now)
            state = {
                "fresh": "receiving_data",
                "delayed": "delayed",
                "stale": "stale",
                "offline": "error",
            }[freshness["status"]]
            last_received, age = receipt, freshness["age_seconds"]
        result.append({
            "telemetry_source": source,
            "status": state,
            "last_received_at": last_received,
            "age_seconds": age,
        })
    return result


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
