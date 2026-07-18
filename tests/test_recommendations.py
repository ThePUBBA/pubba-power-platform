from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import main
from services.recommendations import (
    ADVISORY_NOTICE,
    RecommendationAssumptions,
    calculate_opportunity_economics,
    rank_portfolio_recommendations,
    recommend_asset,
)


NOW = datetime(2026, 7, 18, 3, tzinfo=timezone.utc)
ASSUMPTIONS = RecommendationAssumptions(
    round_trip_efficiency=0.80, variable_om_per_mwh=0,
    market_stale_seconds=1200,
)


def asset(**updates):
    value = {
        "asset_id": "BAT-1", "asset_name": "Battery One", "status": "active",
        "power_mw": 10, "energy_mwh": 40, "duration_hours": 4,
        "lease_cost_monthly": 0, "location": "TH_NP15_GEN-APND",
        "total_dispatches": 2, "average_profit_per_dispatch": 500,
    }
    value.update(updates)
    return value


def market(prices, *, current=None, updated_at=None, status="connected"):
    current = prices[-1] if current is None and prices else current
    return {
        "status": status, "location": "TH_NP15_GEN-APND", "market": "RTM",
        "current_price_per_mwh": current,
        "updated_at": updated_at or (NOW - timedelta(minutes=5)).isoformat(),
        "price_points": [
            {"timestamp": (NOW - timedelta(minutes=5 * (len(prices) - index))).isoformat(),
             "price_per_mwh": price}
            for index, price in enumerate(prices)
        ],
    }


def telemetry(**updates):
    value = {
        "asset_id": "BAT-1", "recorded_at": (NOW - timedelta(minutes=1)).isoformat(),
        "readiness": {"state": "ready_to_discharge", "explanation": "Ready to discharge"},
    }
    value.update(updates)
    return value


def recommendation(prices, **kwargs):
    asset_record = kwargs.pop("asset_record", asset())
    telemetry_record = kwargs.pop("telemetry_record", None)
    return recommend_asset(
        asset=asset_record, market=market(prices, **kwargs),
        telemetry=telemetry_record, now=NOW,
        assumptions=ASSUMPTIONS,
    )


def test_strong_and_potential_discharge_opportunities_are_explainable():
    strong = recommendation([10, 20, 30, 40, 100])
    potential = recommendation([10, 20, 30, 40, 50, 60, 70, 80, 90, 60])
    assert strong["recommendation"] == "Strong discharge opportunity"
    assert potential["recommendation"] == "Potential discharge opportunity"
    assert "percentile" in strong["explanation"]
    assert strong["advisory_notice"] == ADVISORY_NOTICE
    assert strong["actionable"] is False


def test_hold_and_charging_opportunity_states():
    hold = recommendation([10, 20, 40, 45, 50, 60, 70, 80, 90, 100, 55])
    potential = recommendation([10, 20, 40, 50, 60, 70, 80, 90, 100, 25])
    strong = recommendation([20, 30, 40, 50, 0])
    assert hold["recommendation"] == "Hold"
    assert potential["recommendation"] == "Potential charging opportunity"
    assert strong["recommendation"] == "Strong charging opportunity"


def test_missing_and_stale_market_data_issue_no_recommendation():
    missing = recommendation([], status="unavailable", current=None)
    stale = recommendation(
        [10, 20, 100], updated_at=(NOW - timedelta(hours=2)).isoformat()
    )
    assert missing["recommendation"] == "Insufficient operational data"
    assert stale["recommendation"] == "Insufficient operational data"
    assert stale["market_status"] == "stale"
    assert stale["actionable"] is False


def test_retired_asset_is_never_an_actionable_candidate():
    result = recommendation([10, 20, 100], asset_record=asset(status="retired"))
    assert result["recommendation"] == "Insufficient operational data"
    assert result["opportunity_score"] == 0
    assert result["actionable"] is False


def test_break_even_economics_and_efficiency_are_explicit():
    result = calculate_opportunity_economics(
        asset=asset(), current_price=100, observed_prices=[10, 20, 30, 40, 100],
        assumptions=ASSUMPTIONS,
    )
    assert result["estimated_charging_price_per_mwh"] == 20
    assert result["charging_energy_required_mwh"] == 50
    assert result["estimated_charging_cost"] == 1000
    assert result["estimated_discharge_revenue"] == 4000
    assert result["estimated_gross_profit"] == 3000
    assert result["break_even_discharge_price_per_mwh"] == 25


def test_live_readiness_is_additive_and_direction_specific():
    ready = recommendation(
        [10, 20, 30, 40, 100], telemetry_record=telemetry()
    )
    wrong_direction = recommendation(
        [20, 30, 40, 50, 0], telemetry_record=telemetry()
    )
    assert ready["telemetry_status"] == "fresh"
    assert ready["actionable"] is True
    assert wrong_direction["recommendation"] == "Strong charging opportunity"
    assert wrong_direction["actionable"] is False


def test_ranking_excludes_retired_asset_from_best_candidate():
    result = rank_portfolio_recommendations(
        assets=[asset(asset_id="ACTIVE"), asset(asset_id="RETIRED", status="retired")],
        market=market([10, 20, 100]), now=NOW, assumptions=ASSUMPTIONS,
    )
    assert result["best_candidate_asset_id"] == "ACTIVE"
    assert result["advisory_only"] is True
    assert result["autonomous_dispatch"] is False


def _dashboard_payload():
    return {
        "portfolio": {}, "period": {}, "financial": {}, "series": {
            "market_prices": market([10, 20, 100])["price_points"]
        },
        "status": {"market_data": "connected"},
        "kpis": {"current_market_price_per_mwh": 100},
        "metadata": {
            "market_location": "TH_NP15_GEN-APND", "market_type": "RTM",
            "market_updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        },
        "telemetry": {"assets": []},
    }


def test_recommendation_api_shape_and_asset_lookup(monkeypatch):
    monkeypatch.setattr(main, "build_dashboard_summary", lambda **kwargs: _dashboard_payload())
    monkeypatch.setattr(main, "get_asset_performance", lambda: [asset()])
    client = TestClient(main.app)
    portfolio = client.get("/recommendations/portfolio")
    detail = client.get("/recommendations/assets/BAT-1")
    missing = client.get("/recommendations/assets/UNKNOWN")
    assert portfolio.status_code == 200
    assert portfolio.json()["autonomous_dispatch"] is False
    assert detail.status_code == 200
    assert set(("asset_id", "market_price_per_mwh", "opportunity_score", "recommendation",
                "estimated_economics", "operational_readiness", "telemetry_status",
                "primary_drivers", "risks", "generated_at")) <= set(detail.json())
    assert missing.status_code == 404
