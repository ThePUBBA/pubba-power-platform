"""Deterministic, explainable, advisory market opportunity recommendations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from services.telemetry import parse_timestamp, telemetry_freshness


ADVISORY_NOTICE = (
    "Advisory market analysis only. This recommendation does not execute dispatch "
    "or a market transaction and does not guarantee profit."
)


@dataclass(frozen=True)
class RecommendationAssumptions:
    round_trip_efficiency: float = 0.80
    variable_om_per_mwh: float = 0.0
    market_stale_seconds: int = 1200

    @classmethod
    def from_environment(cls) -> "RecommendationAssumptions":
        values = cls(
            round_trip_efficiency=float(
                os.getenv("RECOMMENDATION_ROUND_TRIP_EFFICIENCY", "0.80")
            ),
            variable_om_per_mwh=float(
                os.getenv("RECOMMENDATION_VARIABLE_OM_PER_MWH", "0")
            ),
            market_stale_seconds=int(
                os.getenv("RECOMMENDATION_MARKET_STALE_SECONDS", "1200")
            ),
        )
        if not 0 < values.round_trip_efficiency <= 1:
            raise RuntimeError("Recommendation round-trip efficiency must be in (0, 1]")
        if values.variable_om_per_mwh < 0 or values.market_stale_seconds <= 0:
            raise RuntimeError("Recommendation cost and freshness assumptions are invalid")
        return values

    def as_dict(self) -> dict[str, Any]:
        return {
            "round_trip_efficiency": self.round_trip_efficiency,
            "variable_om_per_mwh": self.variable_om_per_mwh,
            "market_stale_seconds": self.market_stale_seconds,
            "classification": "configured planning assumptions, not telemetry",
        }


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    return 100 * sum(item <= value for item in values) / len(values)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[round((len(ordered) - 1) * fraction)]


def calculate_opportunity_economics(
    *, asset: dict[str, Any], current_price: float,
    observed_prices: list[float], assumptions: RecommendationAssumptions,
) -> dict[str, Any]:
    """Estimate one configured full cycle without claiming operational availability."""
    power_mw = max(0.0, _number(asset.get("power_mw")))
    energy_mwh = max(0.0, _number(asset.get("energy_mwh")))
    duration = max(0.0, _number(asset.get("duration_hours")))
    if not duration and power_mw:
        duration = energy_mwh / power_mw
    configured_energy = min(energy_mwh, power_mw * duration) if duration else energy_mwh
    charge_price = _quantile(observed_prices, 0.25)
    charging_energy = configured_energy / assumptions.round_trip_efficiency
    charging_cost = charging_energy * charge_price
    discharge_revenue = configured_energy * current_price
    variable_cost = configured_energy * assumptions.variable_om_per_mwh
    lease_cost = max(0.0, _number(asset.get("lease_cost_monthly"))) / 30
    gross_profit = discharge_revenue - charging_cost - variable_cost - lease_cost
    break_even = (
        charge_price / assumptions.round_trip_efficiency
        + assumptions.variable_om_per_mwh
        + (lease_cost / configured_energy if configured_energy else 0)
    )
    return {
        "configured_cycle_energy_mwh": configured_energy,
        "estimated_charging_price_per_mwh": charge_price,
        "charging_energy_required_mwh": charging_energy,
        "estimated_charging_cost": charging_cost,
        "estimated_discharge_revenue": discharge_revenue,
        "estimated_gross_profit": gross_profit,
        "estimated_margin_pct": (
            gross_profit / discharge_revenue * 100 if discharge_revenue else None
        ),
        "estimated_revenue_per_mwh": current_price,
        "estimated_spread_per_mwh": current_price - break_even,
        "break_even_discharge_price_per_mwh": break_even,
        "current_market_price_per_mwh": current_price,
        "daily_allocated_lease_cost": lease_cost,
        "variable_operating_cost": variable_cost,
    }


def _market_state(
    market: dict[str, Any], *, now: datetime, assumptions: RecommendationAssumptions,
) -> tuple[list[float], float | None, str, int | None]:
    prices = [
        _number(point.get("price_per_mwh"), float("nan"))
        for point in market.get("price_points") or []
    ]
    prices = [price for price in prices if isfinite(price)]
    current = market.get("current_price_per_mwh")
    current_price = _number(current, float("nan"))
    if market.get("status") != "connected" or not prices or not isfinite(current_price):
        return prices, None, "unavailable", None
    try:
        updated = parse_timestamp(market.get("updated_at"))
    except ValueError:
        return prices, current_price, "unavailable", None
    age = max(0, int((now - updated).total_seconds()))
    status = "fresh" if age <= assumptions.market_stale_seconds else "stale"
    return prices, current_price, status, age


def recommend_asset(
    *, asset: dict[str, Any], market: dict[str, Any], telemetry: dict[str, Any] | None,
    now: datetime | None = None,
    assumptions: RecommendationAssumptions | None = None,
) -> dict[str, Any]:
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    config = assumptions or RecommendationAssumptions.from_environment()
    prices, current, market_status, market_age = _market_state(
        market, now=generated, assumptions=config
    )
    asset_id = str(asset.get("asset_id") or "")
    lifecycle = str(asset.get("status") or "unknown").lower()
    telemetry_status = "unavailable"
    readiness = {
        "state": "telemetry_unavailable",
        "explanation": "Operational readiness awaiting live telemetry.",
    }
    if telemetry:
        freshness = telemetry_freshness(telemetry.get("recorded_at"), now=generated)
        telemetry_status = freshness["status"]
        readiness = telemetry.get("readiness") or readiness

    risks: list[str] = []
    missing = []
    if not telemetry:
        missing.extend(["live state of charge", "asset availability", "live power limits"])
        risks.append("Operational readiness cannot be confirmed because live telemetry is unavailable.")
    elif telemetry_status in {"stale", "offline", "unavailable"}:
        risks.append("Telemetry is not current enough to confirm operational readiness.")
    if market_status == "unavailable":
        risks.append("Current CAISO market data is unavailable.")
    elif market_status == "stale":
        risks.append("CAISO market data is stale; no market recommendation is issued.")
    if lifecycle != "active":
        risks.append(f"Asset lifecycle status is {lifecycle}; it is not an actionable candidate.")

    if current is None or market_status != "fresh" or lifecycle != "active":
        return {
            "asset_id": asset_id,
            "asset_name": str(asset.get("asset_name") or asset_id),
            "market_price_per_mwh": current,
            "market_status": market_status,
            "market_age_seconds": market_age,
            "opportunity_score": 0,
            "recommendation": "Insufficient operational data",
            "market_opportunity": "No current market opportunity is issued.",
            "estimated_economics": None,
            "operational_readiness": readiness,
            "telemetry_status": telemetry_status,
            "primary_drivers": [], "risks": risks,
            "missing_operational_data": missing,
            "explanation": risks[0] if risks else "Required inputs are unavailable.",
            "assumptions": config.as_dict(),
            "simulation_inputs": None,
            "advisory_notice": ADVISORY_NOTICE,
            "generated_at": generated.isoformat(),
            "actionable": False,
        }

    economics = calculate_opportunity_economics(
        asset=asset, current_price=current, observed_prices=prices, assumptions=config
    )
    percentile = _percentile(prices, current)
    recent = prices[-5:-1]
    recent_average = sum(recent) / len(recent) if recent else current
    movement = current - recent_average
    spread = economics["estimated_spread_per_mwh"]
    historical_profit = _number(asset.get("average_profit_per_dispatch"))
    extremity = abs(percentile - 50) / 50
    economic_signal = min(abs(spread) / max(abs(economics["break_even_discharge_price_per_mwh"]), 20), 1)
    movement_signal = min(abs(movement) / max(abs(recent_average), 20), 1)
    history_signal = 10 if historical_profit > 0 else 5 if not asset.get("total_dispatches") else 0
    score = round(min(100, extremity * 55 + economic_signal * 25 + movement_signal * 10 + history_signal))

    strong_spread = max(5.0, abs(economics["break_even_discharge_price_per_mwh"]) * 0.10)
    if percentile >= 80 and spread >= strong_spread:
        recommendation = "Strong discharge opportunity"
    elif percentile >= 60 and spread > 0:
        recommendation = "Potential discharge opportunity"
    elif percentile <= 20 and current <= economics["estimated_charging_price_per_mwh"]:
        recommendation = "Strong charging opportunity"
    elif percentile <= 40:
        recommendation = "Potential charging opportunity"
    else:
        recommendation = "Hold"

    direction = "discharge" if "discharge" in recommendation.lower() else (
        "charge" if "charging" in recommendation.lower() else "hold"
    )
    drivers = [
        f"Current price is in the {percentile:.0f}th percentile of the observed CAISO window.",
        f"Current price is ${spread:,.2f}/MWh {'above' if spread >= 0 else 'below'} estimated break-even.",
        f"Recent price movement is {movement:+,.2f}/MWh.",
    ]
    if asset.get("total_dispatches"):
        drivers.append(
            f"Historical average profit is ${historical_profit:,.2f} per recorded dispatch."
        )
    market_opportunity = (
        f"{recommendation} detected from current market pricing."
        if recommendation != "Hold" else "Market pricing does not currently clear a charge or discharge threshold."
    )
    explanation = (
        f"{recommendation} score {score}/100 because current CAISO price is in the "
        f"{percentile:.0f}th percentile and estimated spread is {spread:+,.2f}/MWh."
    )
    return {
        "asset_id": asset_id,
        "asset_name": str(asset.get("asset_name") or asset_id),
        "market_price_per_mwh": current,
        "market_status": market_status,
        "market_age_seconds": market_age,
        "market_price_percentile": percentile,
        "recent_price_movement_per_mwh": movement,
        "opportunity_score": score,
        "recommendation": recommendation,
        "market_opportunity": market_opportunity,
        "estimated_economics": economics,
        "operational_readiness": readiness,
        "telemetry_status": telemetry_status,
        "primary_drivers": drivers,
        "risks": risks,
        "missing_operational_data": missing,
        "explanation": explanation,
        "assumptions": config.as_dict(),
        "simulation_inputs": {
            "asset_id": asset_id,
            "location": asset.get("location") or market.get("location"),
            "market": market.get("market") or "RTM",
            "power_mw": _number(asset.get("power_mw")),
            "duration_hours": _number(asset.get("duration_hours")) or (
                _number(asset.get("energy_mwh")) / _number(asset.get("power_mw"))
                if _number(asset.get("power_mw")) else 0
            ),
            "round_trip_efficiency": config.round_trip_efficiency,
            "storage_fee_per_mwh": 0,
            "variable_om_per_mwh": config.variable_om_per_mwh,
        },
        "advisory_notice": ADVISORY_NOTICE,
        "generated_at": generated.isoformat(),
        "actionable": bool(
            telemetry
            and telemetry_status == "fresh"
            and (
                direction == "charge" and readiness.get("state") in {
                    "ready_to_charge", "ready_charge_discharge",
                }
                or direction == "discharge" and readiness.get("state") in {
                    "ready_to_discharge", "ready_charge_discharge",
                }
            )
        ),
    }


def rank_portfolio_recommendations(
    *, assets: list[dict[str, Any]], market: dict[str, Any],
    telemetry_records: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    assumptions: RecommendationAssumptions | None = None,
) -> dict[str, Any]:
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    telemetry_by_asset = {
        str(item.get("asset_id") or ""): item for item in telemetry_records or []
    }
    recommendations = [
        recommend_asset(
            asset=asset, market=market,
            telemetry=telemetry_by_asset.get(str(asset.get("asset_id") or "")),
            now=generated, assumptions=assumptions,
        )
        for asset in assets
    ]
    recommendations.sort(
        key=lambda item: (
            str(next((asset.get("status") for asset in assets if str(asset.get("asset_id")) == item["asset_id"]), "")).lower() == "active",
            item["opportunity_score"], item["asset_id"],
        ),
        reverse=True,
    )
    candidates = [
        item for item in recommendations
        if item["recommendation"] != "Insufficient operational data"
    ]
    return {
        "generated_at": generated.isoformat(),
        "advisory_only": True,
        "autonomous_dispatch": False,
        "market_status": recommendations[0]["market_status"] if recommendations else "unavailable",
        "highest_opportunity_score": candidates[0]["opportunity_score"] if candidates else 0,
        "best_candidate_asset_id": candidates[0]["asset_id"] if candidates else None,
        "recommendations": recommendations,
    }
