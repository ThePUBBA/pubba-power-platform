from dashboard.api_client import DashboardApiError
from dashboard.charts import trend_figure
from dashboard.pages.overview import _market_day_axis
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


def test_market_axis_covers_entire_local_day_with_two_hour_ticks():
    day_range, ticks = _market_day_axis(
        [{"timestamp": "2026-07-17T15:45:00-07:00"}],
        "America/Los_Angeles",
    )

    assert day_range == [
        "2026-07-17T00:00:00-07:00",
        "2026-07-18T00:00:00-07:00",
    ]
    assert len(ticks) == 12
    assert ticks[0] == "2026-07-17T00:00:00-07:00"
    assert ticks[-1] == "2026-07-17T22:00:00-07:00"
