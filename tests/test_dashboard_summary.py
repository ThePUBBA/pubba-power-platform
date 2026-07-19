from datetime import datetime, timezone

import pandas as pd

from services.dashboard_summary import build_dashboard_summary


PORTFOLIO = {
    "id": "portfolio-pubba",
    "code": "ONLY1",
    "name": "PUBBA Power",
    "default_market": "CAISO",
    "reporting_timezone": "America/Los_Angeles",
    "currency_code": "USD",
}
NOW = datetime(2026, 7, 15, 18, tzinfo=timezone.utc)


def dispatch(**values):
    record = {
        "id": "row-1",
        "dispatch_id": "dispatch:one",
        "asset_id": "asset-1",
        "status": "simulated",
        "dispatch_timestamp": "2026-07-15T10:00:00Z",
        "updated_at": "2026-07-15T10:00:00Z",
        "purchased_energy_mwh": "50",
        "sold_energy_mwh": "40",
        "discharge_revenue": "3200",
        "charging_cost": "1000",
        "net_profit": "2000",
        "average_buy_price_per_mwh": "20",
        "average_sell_price_per_mwh": "80",
        "location": "TH_NP15_GEN-APND",
    }
    record.update(values)
    return record


def build(records, market_loader=lambda **kwargs: pd.DataFrame()):
    return build_dashboard_summary(
        now=NOW,
        portfolio_resolver=lambda: PORTFOLIO,
        records_loader=lambda portfolio: ([{
            "id": "asset-1", "status": "active", "power_mw": 10,
            "energy_mwh": 40, "updated_at": "2026-07-15T09:00:00Z",
        }], records),
        market_loader=market_loader,
    )


def test_executive_kpis_use_reporting_timezone_and_do_not_invent_values():
    result = build([dispatch()])

    assert result["kpis"]["today_revenue"] == 3200
    assert result["kpis"]["today_profit"] == 2000
    assert result["kpis"]["today_dispatches"] == 1
    assert result["kpis"]["available_capacity_mw"] == 10
    assert result["kpis"]["portfolio_value"] is None
    assert result["kpis"]["battery_state_of_charge_pct"] is None
    assert result["data_quality"]["financial_values"] == "calculated_estimate"


def test_duplicate_dispatch_identity_is_counted_once_using_latest_record():
    older = dispatch(net_profit="100", updated_at="2026-07-15T10:00:00Z")
    newer = dispatch(net_profit="250", updated_at="2026-07-15T11:00:00Z")

    result = build([older, newer])

    assert result["kpis"]["today_dispatches"] == 1
    assert result["kpis"]["today_profit"] == 250
    assert len(result["series"]["dispatches"]) == 1


def test_previous_local_day_is_not_in_today_kpis_but_remains_in_history():
    result = build([dispatch(dispatch_timestamp="2026-07-15T06:59:59Z")])

    assert result["kpis"]["today_dispatches"] == 0
    assert len(result["series"]["daily"]) == 1
    assert result["series"]["daily"][0]["date"] == "2026-07-14"


def test_market_snapshot_is_live_when_present_and_honestly_unavailable_otherwise():
    requested_dates = []

    def market_loader(**kwargs):
        requested_dates.append(kwargs["date"])
        assert kwargs["days"] == 2
        return pd.DataFrame([
            {"timestamp": "2026-07-14T11:55:00-0700", "lmp_prc": 35.0},
            {"timestamp": "2026-07-15T11:55:00-0700", "lmp_prc": 42.5},
        ])

    live = build([dispatch()], market_loader=market_loader)
    unavailable = build([dispatch()])

    assert live["status"]["market_data"] == "connected"
    assert live["kpis"]["current_market_price_per_mwh"] == 42.5
    assert live["metadata"]["market_statistics"] == {
        "minimum_price_per_mwh": 42.5,
        "maximum_price_per_mwh": 42.5,
        "average_price_per_mwh": 42.5,
        "price_spread_per_mwh": 0.0,
    }
    assert live["series"]["dispatches"][0]["charging_cost"] == 1000
    assert live["series"]["dispatches"][0]["market"] is None
    assert requested_dates == ["2026-07-14"]
    assert live["series"]["previous_market_prices"] == [{
        "timestamp": "2026-07-14T11:55:00-0700", "price_per_mwh": 35.0,
    }]
    assert unavailable["status"]["market_data"] == "unavailable"
    assert unavailable["series"]["market_prices"] == []
    assert unavailable["series"]["previous_market_prices"] == []
