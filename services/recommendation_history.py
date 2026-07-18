"""Immutable recommendation snapshots, explicit links, and outcome evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from services.recommendations import RECOMMENDATION_ENGINE_VERSION


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def recommendation_snapshot(
    recommendation: dict[str, Any], *, portfolio_id: str, asset: dict[str, Any],
) -> dict[str, Any]:
    economics = recommendation.get("estimated_economics") or {}
    assumptions = recommendation.get("assumptions") or {}
    readiness = recommendation.get("operational_readiness") or {}
    snapshot = {
        "portfolio_id": portfolio_id,
        "asset_id": recommendation["asset_id"],
        "generated_at": recommendation["generated_at"],
        "market_timestamp": recommendation.get("market_timestamp"),
        "market_price": recommendation.get("market_price_per_mwh"),
        "market_node": (recommendation.get("simulation_inputs") or {}).get("location"),
        "opportunity_score": recommendation["opportunity_score"],
        "recommendation": recommendation["recommendation"],
        "recommendation_direction": recommendation["recommendation_direction"],
        "estimated_charging_cost": economics.get("estimated_charging_cost"),
        "estimated_discharge_revenue": economics.get("estimated_discharge_revenue"),
        "estimated_gross_profit": economics.get("estimated_gross_profit"),
        "estimated_margin": economics.get("estimated_margin_pct"),
        "estimated_break_even_price": economics.get(
            "break_even_discharge_price_per_mwh"
        ),
        "estimated_spread": economics.get("estimated_spread_per_mwh"),
        "round_trip_efficiency_assumption": assumptions.get(
            "round_trip_efficiency"
        ),
        "variable_om_assumption": assumptions.get("variable_om_per_mwh"),
        "lease_cost_assumption": max(0.0, _number(asset.get("lease_cost_monthly")) or 0),
        "telemetry_available": bool(recommendation.get("telemetry_available")),
        "operational_readiness": str(
            readiness.get("state") or "telemetry_unavailable"
        ),
        "telemetry_timestamp": recommendation.get("telemetry_timestamp"),
        "explanation": recommendation["explanation"],
        "drivers": list(recommendation.get("primary_drivers") or []),
        "risks": list(recommendation.get("risks") or []),
        "missing_operational_inputs": list(
            recommendation.get("missing_operational_data") or []
        ),
        "recommendation_engine_version": recommendation.get(
            "recommendation_engine_version", RECOMMENDATION_ENGINE_VERSION
        ),
    }
    fingerprint_fields = {
        key: value for key, value in snapshot.items() if key != "generated_at"
    }
    canonical = json.dumps(fingerprint_fields, sort_keys=True, separators=(",", ":"))
    snapshot["snapshot_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return snapshot


def evaluate_outcome(
    record: dict[str, Any], *, simulation: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if dispatch:
        status = str(dispatch.get("status") or "").lower()
        state = (
            "dispatch_completed" if status == "completed"
            else "simulation_only" if status == "simulated"
            else "dispatch_pending"
        )
    elif simulation:
        state = "simulation_only"
    else:
        state = "no_action_taken"
    estimated = {
        "revenue": _number(record.get("estimated_discharge_revenue")),
        "charging_cost": _number(record.get("estimated_charging_cost")),
        "profit": _number(record.get("estimated_gross_profit")),
        "margin_pct": _number(record.get("estimated_margin")),
    }
    completed_dispatch = dispatch if dispatch and str(dispatch.get("status") or "").lower() == "completed" else None
    realized = {
        "revenue": _number(completed_dispatch.get("discharge_revenue")) if completed_dispatch else None,
        "charging_cost": _number(completed_dispatch.get("charging_cost")) if completed_dispatch else None,
        "profit": _number(completed_dispatch.get("net_profit")) if completed_dispatch else None,
        "margin_pct": None,
    }
    if realized["revenue"] not in (None, 0) and realized["profit"] is not None:
        realized["margin_pct"] = realized["profit"] / realized["revenue"] * 100
    if completed_dispatch and all(realized[key] is None for key in ("revenue", "charging_cost", "profit")):
        state = "outcome_unavailable"
    variance = {}
    for key in ("revenue", "charging_cost", "profit", "margin_pct"):
        expected, actual = estimated[key], realized[key]
        absolute = actual - expected if expected is not None and actual is not None else None
        percentage = (
            absolute / abs(expected) * 100
            if absolute is not None and expected not in (None, 0) else None
        )
        variance[key] = {"absolute": absolute, "percentage_error": percentage}
    return {
        "status": state,
        "estimated": estimated,
        "realized": realized,
        "variance": variance,
        "quality_assessment": "not_enough_linked_outcomes",
    }


def decision_timeline(
    record: dict[str, Any], *, simulation: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events = [
        {"event": "recommendation_generated", "timestamp": record.get("generated_at"), "attribution": "PUBBA Power"},
        {"event": "recommendation_captured", "timestamp": record.get("captured_at") or record.get("created_at"), "attribution": "system"},
    ]
    if record.get("acknowledged_at"):
        events.append({
            "event": "recommendation_acknowledged",
            "timestamp": record["acknowledged_at"],
            "attribution": record.get("acknowledgement_attribution") or "system",
        })
    if simulation and record.get("simulation_linked_at"):
        events.append({"event": "simulation_linked", "timestamp": record["simulation_linked_at"], "attribution": "system"})
    if dispatch and record.get("dispatch_linked_at"):
        events.append({"event": "dispatch_linked", "timestamp": record["dispatch_linked_at"], "attribution": "system"})
        if str(dispatch.get("status") or "").lower() == "completed":
            events.append({
                "event": "dispatch_completed",
                "timestamp": dispatch.get("updated_at") or dispatch.get("discharge_end"),
                "attribution": "dispatch ledger",
            })
    return sorted(
        [event for event in events if event.get("timestamp")],
        key=lambda event: str(event["timestamp"]),
    )


def history_detail(
    record: dict[str, Any], *, simulation: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    simulation_comparison = None
    if simulation:
        estimated_profit = _number(record.get("estimated_gross_profit"))
        simulation_profit = _number(simulation.get("estimated_net_margin"))
        simulation_comparison = {
            "recommendation_estimated_profit": estimated_profit,
            "simulation_estimated_profit": simulation_profit,
            "profit_difference": (
                simulation_profit - estimated_profit
                if estimated_profit is not None and simulation_profit is not None else None
            ),
            "recommendation_estimated_revenue": _number(
                record.get("estimated_discharge_revenue")
            ),
            "simulation_estimated_revenue": _number(
                simulation.get("discharge_revenue")
            ),
            "recommendation_estimated_charging_cost": _number(
                record.get("estimated_charging_cost")
            ),
            "simulation_estimated_charging_cost": _number(
                simulation.get("charging_cost")
            ),
        }
    return {
        **record,
        "simulation": simulation,
        "dispatch": dispatch,
        "simulation_comparison": simulation_comparison,
        "outcome": evaluate_outcome(record, simulation=simulation, dispatch=dispatch),
        "decision_timeline": decision_timeline(
            record, simulation=simulation, dispatch=dispatch
        ),
    }


def history_analytics(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(records)
    linked_dispatches = [record for record in records if record.get("dispatch_id")]
    profits = [
        _number(record.get("estimated_gross_profit")) for record in records
        if _number(record.get("estimated_gross_profit")) is not None
    ]
    scores = [_number(record.get("opportunity_score")) for record in records]
    scores = [score for score in scores if score is not None]
    realized_profits = [
        _number((record.get("outcome") or {}).get("realized", {}).get("profit"))
        for record in records
    ]
    realized_profits = [value for value in realized_profits if value is not None]
    profit_variances = [
        _number((record.get("outcome") or {}).get("variance", {}).get("profit", {}).get("absolute"))
        for record in records
    ]
    profit_variances = [value for value in profit_variances if value is not None]
    return {
        "sample_size": count,
        "recommendations_captured": count,
        "recommendations_acknowledged": sum(bool(item.get("acknowledged_at")) for item in records),
        "recommendations_simulated": sum(bool(item.get("simulation_id")) for item in records),
        "recommendations_linked_to_dispatch": len(linked_dispatches),
        "average_opportunity_score": sum(scores) / len(scores) if scores else None,
        "estimated_opportunity_value": sum(profits) if profits else None,
        "realized_profit": sum(realized_profits) if realized_profits else None,
        "estimated_vs_realized_profit_variance": (
            sum(profit_variances) if profit_variances else None
        ),
        "linked_outcome_sample_size": len(realized_profits),
        "completed_linked_outcomes": len(realized_profits),
        "accuracy_available": len(realized_profits) >= 10,
        "accuracy_message": (
            "Insufficient linked outcomes for model accuracy analysis."
            if len(realized_profits) < 10
            else "Linked outcomes are available for a separately approved calibration review."
        ),
    }
