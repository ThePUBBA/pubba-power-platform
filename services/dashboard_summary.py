"""Live executive dashboard aggregation built from authoritative backend data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from decimal import Decimal, InvalidOperation
from typing import Callable
from zoneinfo import ZoneInfo

from caiso import CaisoOasisError, fetch_lmp_data
from services.portfolio_summary import (
    COMPLETED_STATUSES,
    PortfolioSummaryError,
    build_portfolio_summary,
    reporting_period_starts,
)
from services.telemetry import (
    TelemetryValidationError,
    calculate_dispatch_readiness,
    normalize_telemetry,
    source_health,
    telemetry_alerts,
    telemetry_freshness,
)
from supabase import (
    SupabaseError,
    get_default_portfolio,
    get_portfolio_summary_records,
    list_portfolio_latest_telemetry,
)


DEFAULT_CAISO_NODE = "TH_NP15_GEN-APND"
ZERO = Decimal("0")


def _decimal(value: object) -> Decimal:
    if value in (None, ""):
        return ZERO
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO
    return number if number.is_finite() else ZERO


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deduplicated_completed(records: list[dict]) -> list[dict]:
    """Keep one completed ledger row per stable dispatch identity."""
    unique: dict[str, dict] = {}
    for index, record in enumerate(records):
        if str(record.get("status", "")).strip().lower() not in COMPLETED_STATUSES:
            continue
        identity = str(record.get("dispatch_id") or record.get("id") or f"row:{index}")
        current = unique.get(identity)
        current_stamp = _timestamp(current.get("updated_at")) if current else None
        candidate_stamp = _timestamp(record.get("updated_at"))
        if current is None or (candidate_stamp and (not current_stamp or candidate_stamp > current_stamp)):
            unique[identity] = record
    return list(unique.values())


def _daily_series(records: list[dict], zone: ZoneInfo) -> list[dict]:
    buckets: dict[str, dict[str, Decimal | int]] = {}
    for record in records:
        stamp = _timestamp(record.get("dispatch_timestamp"))
        if not stamp:
            continue
        day = stamp.astimezone(zone).date().isoformat()
        bucket = buckets.setdefault(
            day, {"revenue": ZERO, "profit": ZERO, "throughput_mwh": ZERO, "dispatches": 0}
        )
        bucket["revenue"] += _decimal(record.get("discharge_revenue"))
        bucket["profit"] += _decimal(record.get("net_profit"))
        bucket["throughput_mwh"] += (
            _decimal(record.get("purchased_energy_mwh"))
            + _decimal(record.get("sold_energy_mwh"))
        )
        bucket["dispatches"] += 1
    return [{"date": day, **values} for day, values in sorted(buckets.items())]


def _dispatch_series(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        stamp = _timestamp(record.get("dispatch_timestamp"))
        if not stamp:
            continue
        rows.append({
            "dispatch_id": record.get("dispatch_id") or record.get("id"),
            "asset_id": record.get("asset_id"),
            "timestamp": stamp,
            "charge_start": _timestamp(record.get("charge_start")),
            "charge_end": _timestamp(record.get("charge_end")),
            "discharge_start": _timestamp(record.get("discharge_start")),
            "discharge_end": _timestamp(record.get("discharge_end")),
            "energy_mwh": _decimal(record.get("sold_energy_mwh") or record.get("energy_mwh")),
            "charge_energy_mwh": _decimal(record.get("purchased_energy_mwh")),
            "discharge_energy_mwh": _decimal(record.get("sold_energy_mwh")),
            "revenue": _decimal(record.get("discharge_revenue")),
            "charging_cost": _decimal(record.get("charging_cost")),
            "profit": _decimal(record.get("net_profit")),
            "market": record.get("market"),
            "location": record.get("location"),
            "data_quality": (
                "calculated_estimate"
                if str(record.get("status", "")).lower() == "simulated"
                else "operational_record"
            ),
        })
    return sorted(rows, key=lambda row: row["timestamp"])


def _market_snapshot(
    *,
    location: str,
    market_loader: Callable[..., object],
    trade_date: str,
) -> dict:
    def load_points(date: str) -> list[dict]:
        frame = market_loader(location=location, market="RTM", date=date)
        records = frame.to_dict(orient="records")
        points = [
            {"timestamp": row.get("timestamp"), "price_per_mwh": row.get("lmp_prc")}
            for row in records
            if row.get("timestamp") and row.get("lmp_prc") is not None
        ]
        points.sort(key=lambda point: str(point["timestamp"]))
        return points

    try:
        points = load_points(trade_date)
        if not points:
            raise CaisoOasisError("CAISO OASIS returned no usable price points")
        previous_date = (
            datetime.fromisoformat(trade_date).date() - timedelta(days=1)
        ).isoformat()
        try:
            previous_points = load_points(previous_date)
        except (CaisoOasisError, ValueError, AttributeError, TypeError):
            previous_points = []
        return {
            "status": "connected",
            "location": location,
            "market": "RTM",
            "current_price_per_mwh": points[-1]["price_per_mwh"],
            "price_points": points,
            "previous_price_points": previous_points,
            "updated_at": points[-1]["timestamp"],
        }
    except (CaisoOasisError, ValueError, AttributeError, TypeError):
        return {
            "status": "unavailable",
            "location": location,
            "market": "RTM",
            "current_price_per_mwh": None,
            "price_points": [],
            "previous_price_points": [],
            "updated_at": None,
        }


def _telemetry_snapshot(
    records: list[dict], *, now: datetime,
) -> dict:
    assets = []
    for record in records:
        try:
            normalized = normalize_telemetry(record, now=now)
        except TelemetryValidationError:
            continue
        freshness = telemetry_freshness(normalized["recorded_at"], now=now)
        readiness = calculate_dispatch_readiness(normalized, now=now).as_dict()
        assets.append({
            **normalized,
            "created_at": record.get("created_at"),
            "freshness": freshness,
            "readiness": readiness,
        })
    ready_charge = {
        "ready_to_charge", "ready_charge_discharge",
    }
    ready_discharge = {
        "ready_to_discharge", "ready_charge_discharge",
    }
    states = [item["readiness"]["state"] for item in assets]
    soc_values = [
        item["state_of_charge_pct"] for item in assets
        if item.get("state_of_charge_pct") is not None
    ]
    charge_values = [
        item["available_charge_power_mw"] for item in assets
        if item.get("available_charge_power_mw") is not None
    ]
    discharge_values = [
        item["available_discharge_power_mw"] for item in assets
        if item.get("available_discharge_power_mw") is not None
    ]
    configured_sources = [
        item.strip()
        for item in os.getenv("TELEMETRY_CONFIGURED_SOURCES", "").split(",")
        if item.strip()
    ]
    return {
        "status": "available" if assets else "unavailable",
        "source_classification": (
            "simulated" if assets and all(item["is_simulated"] for item in assets)
            else "mixed" if any(item["is_simulated"] for item in assets)
            else "operational" if assets else "unavailable"
        ),
        "average_state_of_charge_pct": (
            sum(soc_values) / len(soc_values) if soc_values else None
        ),
        "total_available_charge_power_mw": sum(charge_values) if charge_values else None,
        "total_available_discharge_power_mw": sum(discharge_values) if discharge_values else None,
        "assets_ready_to_charge": sum(state in ready_charge for state in states),
        "assets_ready_to_discharge": sum(state in ready_discharge for state in states),
        "assets_limited": sum(state in {"limited", "telemetry_stale"} for state in states),
        "assets_unavailable": sum(state in {"unavailable", "telemetry_unavailable"} for state in states),
        "assets_stale": sum(item["freshness"]["stale"] for item in assets),
        "source_health": source_health(
            assets, now=now, configured_sources=configured_sources
        ),
        "alerts": telemetry_alerts(assets, now=now),
        "assets": assets,
    }
def build_dashboard_summary(
    *,
    timezone_name: str | None = None,
    include_market: bool = True,
    now: datetime | None = None,
    portfolio_resolver: Callable[[], dict] = get_default_portfolio,
    records_loader: Callable[[dict], tuple[list[dict], list[dict]]] = get_portfolio_summary_records,
    market_loader: Callable[..., object] = fetch_lmp_data,
    telemetry_loader: Callable[[], list[dict]] = list_portfolio_latest_telemetry,
) -> dict:
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    portfolio = portfolio_resolver()
    assets, raw_dispatches = records_loader(portfolio)
    summary = build_portfolio_summary(
        timezone_name=timezone_name,
        now=generated_at,
        portfolio_resolver=lambda: portfolio,
        records_loader=lambda _: (assets, raw_dispatches),
    )
    zone = ZoneInfo(summary["period"]["timezone"])
    completed = _deduplicated_completed(raw_dispatches)
    today_start = reporting_period_starts(generated_at, zone)["today"]
    today = [
        row for row in completed
        if (stamp := _timestamp(row.get("dispatch_timestamp")))
        and today_start <= stamp <= generated_at
    ]
    location = next(
        (str(row["location"]) for row in reversed(completed) if row.get("location")),
        DEFAULT_CAISO_NODE,
    )
    market_trade_date = generated_at.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
    market = _market_snapshot(
        location=location,
        market_loader=market_loader,
        trade_date=market_trade_date,
    ) if include_market else {
        "status": "not_checked", "location": location, "market": "RTM",
        "current_price_per_mwh": None, "price_points": [],
        "previous_price_points": [], "updated_at": None,
    }
    try:
        telemetry = _telemetry_snapshot(telemetry_loader(), now=generated_at)
    except SupabaseError:
        telemetry = _telemetry_snapshot([], now=generated_at)
    today_revenue = sum((_decimal(row.get("discharge_revenue")) for row in today), ZERO)
    today_profit = sum((_decimal(row.get("net_profit")) for row in today), ZERO)
    prices = [
        _decimal(point.get("price_per_mwh")) for point in market["price_points"]
        if point.get("price_per_mwh") is not None
    ]
    return {
        "portfolio": summary["portfolio"],
        "period": summary["period"],
        "kpis": {
            "portfolio_value": None,
            "today_revenue": today_revenue,
            "today_profit": today_profit,
            "available_capacity_mw": summary["fleet"]["power_capacity_mw"],
            "active_assets": summary["fleet"]["active_assets"],
            "today_dispatches": len(today),
            "battery_state_of_charge_pct": telemetry["average_state_of_charge_pct"],
            "current_market_price_per_mwh": market["current_price_per_mwh"],
            "last_api_sync_at": generated_at,
        },
        "data_quality": {
            "financial_values": "calculated_estimate" if any(
                str(row.get("status", "")).lower() == "simulated" for row in completed
            ) else "operational_record",
            "available_capacity": "configured_active_asset_capacity",
            "portfolio_value": "unavailable_no_valuation_source",
            "battery_state_of_charge": telemetry["source_classification"],
        },
        "series": {
            "daily": _daily_series(completed, zone),
            "dispatches": _dispatch_series(completed),
            "market_prices": market["price_points"],
            "previous_market_prices": market["previous_price_points"],
            "state_of_charge": [
                {
                    "asset_id": item["asset_id"],
                    "timestamp": item["recorded_at"],
                    "state_of_charge_pct": item["state_of_charge_pct"],
                    "is_simulated": item["is_simulated"],
                }
                for item in telemetry["assets"]
                if item.get("state_of_charge_pct") is not None
            ],
            "asset_utilization": [],
        },
        "status": {
            "api": "connected",
            "supabase": "connected",
            "market_data": market["status"],
            "simulation_engine": "ready",
            "telemetry": telemetry["status"],
        },
        "telemetry": telemetry,
        "metadata": {
            **summary["metadata"],
            "market_updated_at": market["updated_at"],
            "market_location": location,
            "market_name": portfolio.get("default_market"),
            "market_type": market["market"],
            "market_statistics": {
                "minimum_price_per_mwh": min(prices) if prices else None,
                "maximum_price_per_mwh": max(prices) if prices else None,
                "average_price_per_mwh": (
                    sum(prices, ZERO) / len(prices) if prices else None
                ),
                "price_spread_per_mwh": max(prices) - min(prices) if prices else None,
            },
        },
    }
