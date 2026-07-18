from dashboard.api_client import DashboardApiError
from dashboard.charts import (
    daily_energy_figure,
    daily_financial_figure,
    dispatch_economics_figure,
    observation_mode,
    style_chart,
    trend_figure,
)
from dashboard.pages.overview import (
    _asset_presentation_mode,
    _daily_dispatch_metrics,
    _dispatch_chart_rows,
    _market_day_axis,
)
from dashboard.refresh import STATE_KEY, refresh_dashboard_data


class Client:
    last_latency_ms = 12.5

    def get_dashboard_summary(self, **kwargs):
        return {"kpis": {}, "series": {}}

    def get_portfolio_assets(self):
        self.last_latency_ms = 7.5
        return [{"asset_id": "BAT-001"}]


class FailedClient(Client):
    def get_dashboard_summary(self, **kwargs):
        raise DashboardApiError("temporary failure")


class RecommendationClient(Client):
    def get_portfolio_recommendations(self):
        return {"advisory_only": True, "recommendations": [{"asset_id": "BAT-001"}]}


def test_refresh_stores_success_and_latency():
    state = {}
    payload, error = refresh_dashboard_data(state, Client())

    assert error is None
    assert payload["assets"][0]["asset_id"] == "BAT-001"
    assert payload["latency_ms"] == 20
    assert state[STATE_KEY]["data"] is payload


def test_refresh_failure_preserves_previous_success():
    previous = {"dashboard": {"kpis": {"today_profit": 10}}}
    state = {STATE_KEY: {"data": previous}}

    payload, error = refresh_dashboard_data(state, FailedClient())

    assert payload is previous
    assert error == "temporary failure"


def test_refresh_loads_recommendations_without_direct_storage_access():
    payload, error = refresh_dashboard_data({}, RecommendationClient())

    assert error is None
    assert payload["recommendations"]["advisory_only"] is True


def test_single_point_trend_uses_categorical_axis():
    figure = trend_figure(
        [{"date": "2026-07-17", "revenue": 100}],
        "revenue", name="Revenue", color="#44FFBB", currency=True,
    )

    assert figure.layout.xaxis.type == "category"
    assert figure.layout.yaxis.tickprefix == "$"
    assert figure.layout.yaxis.tickformat == ",.2f"
    assert figure.data[0].mode == "markers"
    assert list(figure.data[0].x) == ["2026-07-17"]


def test_shared_chart_style_uses_single_point_tooltips():
    figure = style_chart(
        trend_figure(
            [{"date": "Jul 17, 2026", "revenue": 100}],
            "revenue",
            name="Revenue",
            color="#44FFBB",
            currency=True,
        ),
        title="Revenue",
    )

    assert figure.layout.hovermode == "closest"


def test_market_axis_extends_two_hours_beyond_latest_interval():
    day_range, ticks = _market_day_axis(
        [{"timestamp": "2026-07-17T15:45:00-07:00"}],
        "America/Los_Angeles",
    )

    assert day_range == [
        "2026-07-17T00:00:00-07:00",
        "2026-07-17T17:45:00-07:00",
    ]
    assert len(ticks) == 9
    assert ticks[0] == "2026-07-17T00:00:00-07:00"
    assert ticks[-1] == "2026-07-17T16:00:00-07:00"


def test_market_axis_never_extends_beyond_midnight():
    day_range, _ = _market_day_axis(
        [{"timestamp": "2026-07-17T23:30:00-07:00"}],
        "America/Los_Angeles",
    )

    assert day_range[-1] == "2026-07-18T00:00:00-07:00"


def dispatch(**overrides):
    row = {
        "timestamp": "2026-07-17T14:45:00+00:00",
        "asset_id": "LDES-Unit-A01",
        "charge_energy_mwh": 50,
        "discharge_energy_mwh": 40,
        "revenue": 1000,
        "charging_cost": 600,
        "profit": 400,
        "market": "RTM",
        "location": "TH_NP15_GEN-APND",
        "data_quality": "calculated_estimate",
    }
    row.update(overrides)
    return row


def test_daily_metrics_use_only_complete_returned_dispatch_values():
    rows = _daily_dispatch_metrics(
        [dispatch(), dispatch(profit=200, revenue=500, charging_cost=300), dispatch(profit=None)],
        "America/Los_Angeles",
    )

    assert len(rows) == 1
    assert rows[0]["revenue"] == 1500
    assert rows[0]["charging_cost"] == 900
    assert rows[0]["profit"] == 600
    assert rows[0]["dispatches"] == 2
    assert rows[0]["profit_margin_label"] == "40.0%"
    assert rows[0]["efficiency_label"] == "80.0%"


def test_executive_chart_builders_use_grouped_categorical_bars():
    daily = _daily_dispatch_metrics([dispatch()], "America/Los_Angeles")
    financial = daily_financial_figure(daily)
    energy = daily_energy_figure(daily)
    dispatch_rows = _dispatch_chart_rows([dispatch()], "America/Los_Angeles")
    economics = dispatch_economics_figure(dispatch_rows)

    assert observation_mode(1) == "single"
    assert observation_mode(3) == "sparse"
    assert observation_mode(4) == "categorical"
    assert len(financial.data) == 3
    assert len(energy.data) == 2
    assert len(economics.data) == 3
    assert financial.layout.barmode == "group"
    assert energy.layout.xaxis.type == "category"
    assert economics.layout.xaxis.type == "category"


def test_duplicate_dispatch_times_receive_unique_readable_labels():
    rows = _dispatch_chart_rows([dispatch(), dispatch(profit=500)], "America/Los_Angeles")

    assert rows[0]["label"] == "Jul 17 · 7:45 AM · #1"
    assert rows[1]["label"] == "Jul 17 · 7:45 AM · #2"
    assert rows[0]["classification"] == "Calculated Estimate"


def test_zero_revenue_and_missing_energy_are_handled_without_fabrication():
    zero_revenue = _daily_dispatch_metrics(
        [dispatch(revenue=0, profit=0)], "America/Los_Angeles"
    )
    missing_energy = _daily_dispatch_metrics(
        [dispatch(charge_energy_mwh=None)], "America/Los_Angeles"
    )

    assert zero_revenue[0]["profit_margin"] is None
    assert zero_revenue[0]["profit_margin_label"] == "Not available"
    assert missing_energy == []


def test_invalid_timestamp_is_excluded_from_charts_but_does_not_raise():
    assert _daily_dispatch_metrics(
        [dispatch(timestamp="not-a-timestamp")], "America/Los_Angeles"
    ) == []
    assert _dispatch_chart_rows(
        [dispatch(timestamp="not-a-timestamp")], "America/Los_Angeles"
    ) == []


def test_mixed_operational_and_calculated_dispatches_use_pattern_distinction():
    rows = _dispatch_chart_rows(
        [dispatch(data_quality="operational"), dispatch(data_quality="calculated_estimate")],
        "America/Los_Angeles",
    )
    figure = dispatch_economics_figure(rows)

    assert list(figure.data[0].marker.pattern.shape) == ["", "/"]
    assert {row["classification"] for row in rows} == {
        "Operational", "Calculated Estimate",
    }


def test_asset_presentation_scales_from_cards_to_table():
    assert _asset_presentation_mode(1) == "cards"
    assert _asset_presentation_mode(3) == "cards"
    assert _asset_presentation_mode(4) == "table"
