from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from services.portfolio_summary import (
    PortfolioSummaryError,
    build_portfolio_summary,
    reporting_period_starts,
)


PORTFOLIO = {
    "id": "portfolio-only1",
    "code": "ONLY1",
    "name": "Only1 Power",
    "default_market": "CAISO",
    "reporting_timezone": "America/Los_Angeles",
    "currency_code": "USD",
}
NOW = datetime(2026, 7, 15, 18, tzinfo=timezone.utc)


def dispatch(status="completed", timestamp="2026-07-15T10:00:00Z", **values):
    record = {
        "status": status,
        "dispatch_timestamp": timestamp,
        "discharge_end": timestamp,
        "updated_at": timestamp,
        "purchased_energy_mwh": "50",
        "sold_energy_mwh": "40",
        "charging_cost": "1000",
        "discharge_revenue": "3200",
        "net_profit": "2000",
        "average_buy_price_per_mwh": "20",
        "average_sell_price_per_mwh": "80",
    }
    record.update(values)
    return record


def build(assets=None, dispatches=None, **kwargs):
    return build_portfolio_summary(
        now=NOW,
        portfolio_resolver=lambda: PORTFOLIO,
        records_loader=lambda portfolio: (assets or [], dispatches or []),
        **kwargs,
    )


def test_reporting_period_boundaries_use_local_calendar_and_monday_week():
    starts = reporting_period_starts(NOW, ZoneInfo("America/Los_Angeles"))

    assert starts["today"] == datetime(2026, 7, 15, 7, tzinfo=timezone.utc)
    assert starts["week"] == datetime(2026, 7, 13, 7, tzinfo=timezone.utc)
    assert starts["month"] == datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
    assert starts["quarter"] == datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
    assert starts["year"] == datetime(2026, 1, 1, 8, tzinfo=timezone.utc)


def test_reporting_period_boundaries_handle_daylight_saving_transition():
    now = datetime(2026, 11, 2, 20, tzinfo=timezone.utc)
    starts = reporting_period_starts(now, ZoneInfo("America/Los_Angeles"))

    assert starts["today"] == datetime(2026, 11, 2, 8, tzinfo=timezone.utc)
    assert starts["month"] == datetime(2026, 11, 1, 7, tzinfo=timezone.utc)


def test_valid_timezone_override_and_date_range_are_applied():
    result = build(
        timezone_name="America/Denver",
        start_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    assert result["period"]["timezone"] == "America/Denver"
    assert result["period"]["start_at"] == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_invalid_timezone_and_reversed_range_fail_clearly():
    with pytest.raises(PortfolioSummaryError, match="Unknown timezone"):
        build(timezone_name="Mars/Olympus")
    with pytest.raises(PortfolioSummaryError, match="on or before"):
        build(
            start_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )


def test_completed_dispatch_kpis_reconcile_and_use_energy_weighting():
    records = [
        dispatch(),
        dispatch(
            timestamp="2026-07-15T11:00:00Z",
            purchased_energy_mwh="25", sold_energy_mwh="20",
            charging_cost="600", discharge_revenue="1800", net_profit="1000",
            average_buy_price_per_mwh="24", average_sell_price_per_mwh="90",
        ),
    ]
    result = build(dispatches=records)

    assert result["financial"]["gross_revenue"] == Decimal("5000")
    assert result["financial"]["charging_cost"] == Decimal("1600")
    assert result["financial"]["net_profit"] == Decimal("3000")
    assert result["financial"]["trading_return"] == Decimal("1.875")
    assert result["financial"]["weighted_average_spread_per_mwh"] == Decimal("62")
    assert result["operations"]["purchased_energy_mwh"] == Decimal("75")
    assert result["operations"]["sold_energy_mwh"] == Decimal("60")
    assert result["operations"]["energy_throughput_mwh"] == Decimal("135")
    assert result["operations"]["total_dispatches"] == 2


@pytest.mark.parametrize("status", ["draft", "scheduled", "cancelled", "failed", "unknown"])
def test_non_completed_dispatch_statuses_are_excluded(status):
    result = build(dispatches=[dispatch(status=status)])
    assert result["operations"]["total_dispatches"] == 0
    assert result["financial"]["net_profit"] == 0


def test_legacy_simulated_status_is_normalized_as_completed():
    assert build(dispatches=[dispatch(status="simulated")])["operations"]["total_dispatches"] == 1


def test_only_active_assets_contribute_to_fleet_and_freshness():
    assets = [
        {"status": "active", "power_mw": "10", "energy_mwh": "40", "updated_at": "2026-07-14T10:00:00Z"},
        {"status": "active", "power_mw": None, "energy_mwh": None, "updated_at": "2026-07-15T09:00:00Z"},
    ]
    result = build(assets=assets)
    assert result["fleet"] == {
        "active_assets": 2,
        "power_capacity_mw": Decimal("10"),
        "energy_capacity_mwh": Decimal("40"),
    }
    assert result["metadata"]["data_freshness_at"] == datetime(2026, 7, 15, 9, tzinfo=timezone.utc)


def test_empty_and_zero_denominator_states_are_deterministic():
    empty = build()
    assert empty["operations"]["last_dispatch_at"] is None
    assert empty["metadata"]["data_freshness_at"] is None
    assert empty["financial"]["trading_return"] == 0
    assert empty["financial"]["weighted_average_spread_per_mwh"] == 0

    zero = build(dispatches=[dispatch(charging_cost="0", sold_energy_mwh="0")])
    assert zero["financial"]["trading_return"] == 0
    assert zero["financial"]["weighted_average_spread_per_mwh"] == 0


def test_malformed_capacity_fails_instead_of_silent_coercion():
    with pytest.raises(PortfolioSummaryError, match="power_mw"):
        build(assets=[{"power_mw": "bad", "energy_mwh": 1}])
