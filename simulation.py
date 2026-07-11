from __future__ import annotations

from arbitrage import analyze_lmp_arbitrage


class StorageSimulationError(ValueError):
    """Raised when storage simulation inputs are invalid."""


def simulate_storage_profit(
    lmp_data,
    power_mw: float,
    duration_hours: float = 8,
    round_trip_efficiency: float = 0.80,
    cycles: float = 1,
    storage_fee_per_mwh: float = 0,
    variable_om_per_mwh: float = 0,
) -> dict:
    """Estimate storage arbitrage revenue from historical LMP data."""

    _validate_positive("power_mw", power_mw)
    _validate_positive("duration_hours", duration_hours)
    _validate_positive("cycles", cycles)
    _validate_non_negative("storage_fee_per_mwh", storage_fee_per_mwh)
    _validate_non_negative("variable_om_per_mwh", variable_om_per_mwh)
    if round_trip_efficiency <= 0 or round_trip_efficiency > 1:
        raise StorageSimulationError(
            "round_trip_efficiency must be greater than 0 and less than or equal to 1"
        )

    arbitrage = analyze_lmp_arbitrage(
        lmp_data,
        duration_hours=duration_hours,
        round_trip_efficiency=round_trip_efficiency,
    )

    energy_capacity_mwh = power_mw * duration_hours
    discharged_energy_mwh = energy_capacity_mwh * cycles
    charging_energy_required_mwh = discharged_energy_mwh / round_trip_efficiency

    average_charging_price = arbitrage["average_charging_price"]
    average_discharging_price = arbitrage["average_discharging_price"]
    charging_cost = charging_energy_required_mwh * average_charging_price
    discharge_revenue = discharged_energy_mwh * average_discharging_price
    gross_arbitrage_margin = discharge_revenue - charging_cost
    storage_lease_cost = discharged_energy_mwh * storage_fee_per_mwh
    variable_operating_cost = discharged_energy_mwh * variable_om_per_mwh
    estimated_net_margin = (
        gross_arbitrage_margin - storage_lease_cost - variable_operating_cost
    )

    return {
        "power_mw": power_mw,
        "duration_hours": duration_hours,
        "round_trip_efficiency": round_trip_efficiency,
        "cycles": cycles,
        "storage_fee_per_mwh": storage_fee_per_mwh,
        "variable_om_per_mwh": variable_om_per_mwh,
        "energy_capacity_mwh": energy_capacity_mwh,
        "charging_energy_required_mwh": charging_energy_required_mwh,
        "discharged_energy_mwh": discharged_energy_mwh,
        "charging_cost": charging_cost,
        "discharge_revenue": discharge_revenue,
        "gross_arbitrage_margin": gross_arbitrage_margin,
        "storage_lease_cost": storage_lease_cost,
        "variable_operating_cost": variable_operating_cost,
        "estimated_net_margin": estimated_net_margin,
        "net_margin_per_mw": estimated_net_margin / power_mw,
        "net_margin_per_mwh_discharged": estimated_net_margin
        / discharged_energy_mwh,
        "arbitrage": arbitrage,
        "charging_window": arbitrage["charging_window"],
        "discharging_window": arbitrage["discharging_window"],
        "assumptions": {
            "charging_cost": "charging_energy_required_mwh * average_charging_price",
            "charging_energy_required_mwh": "discharged_energy_mwh / round_trip_efficiency",
            "discharge_revenue": "discharged_energy_mwh * average_discharging_price",
            "gross_arbitrage_margin": "discharge_revenue - charging_cost",
            "estimated_net_margin": "gross_arbitrage_margin - storage_lease_cost - variable_operating_cost",
            "storage_lease_cost": "discharged_energy_mwh * storage_fee_per_mwh",
            "variable_operating_cost": "discharged_energy_mwh * variable_om_per_mwh",
        },
    }


def _validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise StorageSimulationError(f"{name} must be positive")


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise StorageSimulationError(f"{name} must be greater than or equal to 0")
