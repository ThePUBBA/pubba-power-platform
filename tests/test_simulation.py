from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from simulation import StorageSimulationError, simulate_storage_profit


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


def test_simulate_storage_profit_calculates_storage_revenue():
    result = simulate_storage_profit(
        make_hourly_lmp([100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]),
        power_mw=10,
        duration_hours=4,
        round_trip_efficiency=0.80,
        cycles=1,
        storage_fee_per_mwh=5,
        variable_om_per_mwh=2,
    )

    assert result["energy_capacity_mwh"] == 40
    assert result["discharged_energy_mwh"] == 40
    assert result["charging_energy_required_mwh"] == 50
    assert result["charging_cost"] == 750
    assert result["discharge_revenue"] == 3600
    assert result["gross_arbitrage_margin"] == 2850
    assert result["storage_lease_cost"] == 200
    assert result["variable_operating_cost"] == 80
    assert result["estimated_net_margin"] == 2570
    assert result["net_margin_per_mw"] == 257
    assert result["net_margin_per_mwh_discharged"] == 64.25
    assert result["charging_window"]["start_timestamp"] == "2025-04-01T02:00:00+00:00"
    assert result["discharging_window"]["start_timestamp"] == "2025-04-01T08:00:00+00:00"


def test_simulate_storage_profit_uses_hand_worked_100_percent_efficiency_example():
    result = simulate_storage_profit(
        make_hourly_lmp([5, 10, 100, 80]),
        power_mw=2,
        duration_hours=1,
        round_trip_efficiency=1,
        cycles=1,
        storage_fee_per_mwh=0,
        variable_om_per_mwh=0,
    )

    assert result["energy_capacity_mwh"] == 2
    assert result["discharged_energy_mwh"] == 2
    assert result["charging_energy_required_mwh"] == 2
    assert result["charging_cost"] == 10
    assert result["discharge_revenue"] == 200
    assert result["gross_arbitrage_margin"] == 190
    assert result["storage_lease_cost"] == 0
    assert result["variable_operating_cost"] == 0
    assert result["estimated_net_margin"] == 190
    assert result["net_margin_per_mw"] == 95
    assert result["net_margin_per_mwh_discharged"] == 95


def test_simulate_storage_profit_scales_multiple_cycles_and_costs():
    result = simulate_storage_profit(
        make_hourly_lmp([100, 90, 20, 10, 12, 18, 50, 60, 80, 100, 95, 85]),
        power_mw=10,
        duration_hours=4,
        round_trip_efficiency=0.80,
        cycles=2,
        storage_fee_per_mwh=5,
        variable_om_per_mwh=2,
    )

    assert result["energy_capacity_mwh"] == 40
    assert result["discharged_energy_mwh"] == 80
    assert result["charging_energy_required_mwh"] == 100
    assert result["charging_cost"] == 1500
    assert result["discharge_revenue"] == 7200
    assert result["gross_arbitrage_margin"] == 5700
    assert result["storage_lease_cost"] == 400
    assert result["variable_operating_cost"] == 160
    assert result["estimated_net_margin"] == 5140
    assert result["net_margin_per_mw"] == 514
    assert result["net_margin_per_mwh_discharged"] == 64.25


def test_simulate_storage_profit_handles_negative_lmp_values():
    result = simulate_storage_profit(
        make_hourly_lmp([40, -20, 120, 80]),
        power_mw=5,
        duration_hours=1,
        round_trip_efficiency=1,
    )

    assert result["charging_cost"] == -100
    assert result["discharge_revenue"] == 600
    assert result["gross_arbitrage_margin"] == 700
    assert result["estimated_net_margin"] == 700
    assert result["charging_window"]["average_price"] == -20


def test_simulate_storage_profit_allows_negative_net_margin():
    result = simulate_storage_profit(
        make_hourly_lmp([50, 40, 45, 42]),
        power_mw=10,
        duration_hours=1,
        round_trip_efficiency=0.80,
        storage_fee_per_mwh=10,
        variable_om_per_mwh=5,
    )

    assert result["charging_cost"] == 500
    assert result["discharge_revenue"] == 500
    assert result["gross_arbitrage_margin"] == 0
    assert result["storage_lease_cost"] == 100
    assert result["variable_operating_cost"] == 50
    assert result["estimated_net_margin"] == -150
    assert result["net_margin_per_mwh_discharged"] == -15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("power_mw", 0),
        ("power_mw", -1),
        ("duration_hours", 0),
        ("duration_hours", -1),
        ("cycles", 0),
        ("cycles", -1),
    ],
)
def test_simulate_storage_profit_requires_positive_inputs(field, value):
    kwargs = {
        "power_mw": 10,
        "duration_hours": 1,
        "round_trip_efficiency": 0.80,
        "cycles": 1,
        field: value,
    }

    with pytest.raises(StorageSimulationError, match=f"{field} must be positive"):
        simulate_storage_profit(make_hourly_lmp([1, 2, 3, 4]), **kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage_fee_per_mwh", -1),
        ("variable_om_per_mwh", -1),
    ],
)
def test_simulate_storage_profit_rejects_negative_costs(field, value):
    kwargs = {
        "power_mw": 10,
        "duration_hours": 1,
        "round_trip_efficiency": 0.80,
        "cycles": 1,
        field: value,
    }

    with pytest.raises(StorageSimulationError, match=field):
        simulate_storage_profit(make_hourly_lmp([1, 2, 3, 4]), **kwargs)


@pytest.mark.parametrize("round_trip_efficiency", [0, -0.1, 1.1])
def test_simulate_storage_profit_rejects_invalid_efficiency(round_trip_efficiency):
    with pytest.raises(StorageSimulationError, match="round_trip_efficiency"):
        simulate_storage_profit(
            make_hourly_lmp([1, 2, 3, 4]),
            power_mw=10,
            duration_hours=1,
            round_trip_efficiency=round_trip_efficiency,
        )
