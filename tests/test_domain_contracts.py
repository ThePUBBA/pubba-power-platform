from decimal import Decimal

import pytest

from domain.contracts import (
    AssetStatus,
    DispatchStatus,
    METRIC_VERSION,
    SettlementStatus,
    UtilizationMethod,
)
from domain.metrics import (
    dispatch_window_utilization,
    energy_throughput,
    energy_weighted_spread,
    operational_roi,
    trading_return,
)


def test_phase_2_status_contracts_are_stable():
    assert {status.value for status in AssetStatus} == {
        "draft", "active", "unavailable", "maintenance", "retired"
    }
    assert {status.value for status in DispatchStatus} == {
        "draft", "scheduled", "charging", "holding", "discharging",
        "completed", "cancelled", "failed"
    }
    assert {status.value for status in SettlementStatus} == {
        "not_applicable", "unsettled", "estimated", "settled", "disputed"
    }
    assert METRIC_VERSION == "1.0"


def test_financial_return_definitions():
    assert trading_return(Decimal("25"), Decimal("100")) == Decimal("0.25")
    assert operational_roi(
        Decimal("25"), Decimal("100"), Decimal("10"), Decimal("15")
    ) == Decimal("0.2")
    assert trading_return(Decimal("25"), Decimal("0")) is None


def test_dispatch_window_utilization_identifies_initial_method():
    assert dispatch_window_utilization(
        Decimal("30"), Decimal("10"), Decimal("4")
    ) == Decimal("0.75")
    assert UtilizationMethod.DISPATCH_WINDOW_PROXY.value == "dispatch_window_proxy"


def test_energy_weighted_spread_uses_sold_energy():
    result = energy_weighted_spread(
        [(Decimal("20"), Decimal("1")), (Decimal("40"), Decimal("3"))]
    )
    assert result == Decimal("35")
    assert energy_weighted_spread([]) is None


def test_energy_values_are_explicit_and_non_negative():
    assert energy_throughput(Decimal("10"), Decimal("8")) == Decimal("18")
    with pytest.raises(ValueError, match="non-negative"):
        energy_throughput(Decimal("-1"), Decimal("8"))
