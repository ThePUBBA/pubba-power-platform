"""Backend-owned Phase 2 KPI formulas.

Inputs and outputs use portfolio currency and the units named by each
parameter. Decimal is used to avoid introducing binary floating-point error
into financial calculations.
"""

from decimal import Decimal
from typing import Iterable


ZERO = Decimal("0")


def trading_return(net_profit: Decimal, charging_cost: Decimal) -> Decimal | None:
    """Return net profit / charging cost, or None when it is undefined."""
    if charging_cost == ZERO:
        return None
    return net_profit / charging_cost


def operational_roi(
    net_profit: Decimal,
    charging_cost: Decimal,
    storage_lease_allocation: Decimal,
    variable_operating_cost: Decimal,
) -> Decimal | None:
    """Return profit relative to operational capital at risk."""
    denominator = (
        charging_cost + storage_lease_allocation + variable_operating_cost
    )
    if denominator == ZERO:
        return None
    return net_profit / denominator


def dispatch_window_utilization(
    discharged_energy_mwh: Decimal,
    nameplate_power_mw: Decimal,
    dispatch_duration_hours: Decimal,
) -> Decimal | None:
    """Return the first-release dispatch-window utilization proxy."""
    maximum_dischargeable_energy = nameplate_power_mw * dispatch_duration_hours
    if maximum_dischargeable_energy <= ZERO:
        return None
    return discharged_energy_mwh / maximum_dischargeable_energy


def energy_weighted_spread(
    spread_and_sold_energy: Iterable[tuple[Decimal, Decimal]],
) -> Decimal | None:
    """Return SUM(spread * sold MWh) / SUM(sold MWh)."""
    weighted_total = ZERO
    sold_energy_total = ZERO
    for spread_per_mwh, sold_energy_mwh in spread_and_sold_energy:
        if sold_energy_mwh < ZERO:
            raise ValueError("sold_energy_mwh must be non-negative")
        weighted_total += spread_per_mwh * sold_energy_mwh
        sold_energy_total += sold_energy_mwh
    if sold_energy_total == ZERO:
        return None
    return weighted_total / sold_energy_total


def energy_throughput(
    purchased_energy_mwh: Decimal, sold_energy_mwh: Decimal
) -> Decimal:
    """Return explicitly labelled two-way energy throughput in MWh."""
    if purchased_energy_mwh < ZERO or sold_energy_mwh < ZERO:
        raise ValueError("energy values must be non-negative")
    return purchased_energy_mwh + sold_energy_mwh

