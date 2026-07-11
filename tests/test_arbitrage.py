from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from arbitrage import ArbitrageAnalysisError, analyze_lmp_arbitrage


def make_hourly_lmp(prices):
    start = datetime(2025, 4, 1, tzinfo=timezone.utc)
    rows = []
    for index, price in enumerate(prices):
        interval_start = start + timedelta(hours=index)
        interval_end = interval_start + timedelta(hours=1)
        rows.append(
            {
                "interval_start_gmt": interval_start.isoformat(),
                "interval_end_gmt": interval_end.isoformat(),
                "lmp_prc": price,
            }
        )
    return pd.DataFrame(rows)


def test_analyze_lmp_arbitrage_finds_charge_and_discharge_windows():
    prices = [
        100,
        90,
        20,
        10,
        12,
        18,
        50,
        60,
        80,
        100,
        95,
        85,
    ]

    result = analyze_lmp_arbitrage(
        make_hourly_lmp(prices),
        duration_hours=4,
        round_trip_efficiency=0.80,
    )

    assert result["interval_hours"] == 1
    assert result["intervals_per_window"] == 4
    assert result["charging_window"]["start_timestamp"] == "2025-04-01T02:00:00+00:00"
    assert result["charging_window"]["end_timestamp"] == "2025-04-01T06:00:00+00:00"
    assert result["discharging_window"]["start_timestamp"] == "2025-04-01T08:00:00+00:00"
    assert result["discharging_window"]["end_timestamp"] == "2025-04-01T12:00:00+00:00"
    assert result["average_charging_price"] == 15
    assert result["average_discharging_price"] == 90
    assert result["gross_price_spread"] == 75
    assert result["efficiency_adjusted_spread"] == 57
    assert result["estimated_gross_margin_per_mwh_discharged"] == 71.25


def test_analyze_lmp_arbitrage_rejects_invalid_duration():
    with pytest.raises(ArbitrageAnalysisError, match="duration_hours must be positive"):
        analyze_lmp_arbitrage(make_hourly_lmp([1, 2, 3, 4]), duration_hours=0)


def test_analyze_lmp_arbitrage_rejects_invalid_efficiency():
    with pytest.raises(ArbitrageAnalysisError, match="round_trip_efficiency"):
        analyze_lmp_arbitrage(
            make_hourly_lmp([1, 2, 3, 4]),
            duration_hours=1,
            round_trip_efficiency=1.1,
        )


def test_analyze_lmp_arbitrage_requires_enough_intervals():
    with pytest.raises(ArbitrageAnalysisError, match="not enough LMP intervals"):
        analyze_lmp_arbitrage(make_hourly_lmp([1, 2, 3]), duration_hours=2)


def test_analyze_lmp_arbitrage_requires_price_column():
    data = make_hourly_lmp([1, 2, 3, 4]).drop(columns=["lmp_prc"])

    with pytest.raises(ArbitrageAnalysisError, match="missing required columns"):
        analyze_lmp_arbitrage(data, duration_hours=1)
