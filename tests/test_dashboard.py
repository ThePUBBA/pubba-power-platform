from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.formatting import (
    format_currency,
    format_chart_time_tick,
    format_date,
    format_dispatch_timestamp,
    format_energy,
    format_power,
    format_spread,
    format_timestamp,
    format_trading_return,
)
from dashboard.state import DashboardStateError, custom_date_range, is_empty_summary


def summary():
    return {
        "portfolio": {"currency_code": "USD"},
        "period": {"timezone": "America/Los_Angeles"},
        "financial": {},
        "period_revenue": {},
        "operations": {"total_dispatches": 1},
        "fleet": {"active_assets": 1},
        "metadata": {},
    }


class Response:
    def __init__(self, payload=None, status_code=200, invalid_json=False):
        self.payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("invalid")
        return self.payload


class Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_summary_client_uses_endpoint_and_omits_empty_parameters():
    session = Session(Response(summary()))
    client = Only1ApiClient("https://api.example.test/", session=session)

    assert client.get_portfolio_summary() == summary()
    method, url, kwargs = session.calls[0]
    assert method == "get"
    assert url == "https://api.example.test/portfolio/summary"
    assert kwargs["params"] == {}
    assert kwargs["timeout"] == 10


def test_summary_client_serializes_dates_and_timezone():
    session = Session(Response(summary()))
    client = Only1ApiClient("https://api.example.test", session=session)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, tzinfo=timezone.utc)

    client.get_portfolio_summary(
        start_at=start, end_at=end, timezone_name="America/Denver"
    )

    params = session.calls[0][2]["params"]
    assert params == {
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "timezone": "America/Denver",
    }


def test_dashboard_client_uses_live_summary_endpoint_and_validates_contract():
    payload = {
        "portfolio": {}, "period": {}, "kpis": {}, "data_quality": {},
        "series": {}, "status": {}, "metadata": {},
    }
    session = Session(Response(payload))
    client = Only1ApiClient("https://api.example.test", session=session)

    assert client.get_dashboard_summary(timezone_name="America/Denver") == payload
    method, url, kwargs = session.calls[0]
    assert method == "get"
    assert url == "https://api.example.test/dashboard/summary"
    assert kwargs["params"] == {
        "include_market": "true", "timezone": "America/Denver",
    }

    malformed = Only1ApiClient(
        "https://api.example.test", session=Session(Response({"kpis": {}}))
    )
    with pytest.raises(DashboardApiError) as caught:
        malformed.get_dashboard_summary()
    assert caught.value.code == "invalid_response"


def test_asset_client_uses_existing_fastapi_route():
    session = Session(Response([{"asset_id": "BAT-001"}]))
    client = Only1ApiClient("https://api.example.test", session=session)

    assert client.get_portfolio_assets() == [{"asset_id": "BAT-001"}]
    assert session.calls[0][1] == "https://api.example.test/portfolio/assets"
    assert client.last_latency_ms is not None


def test_recommendation_client_requires_advisory_contract():
    payload = {"advisory_only": True, "recommendations": [{"asset_id": "BAT-001"}]}
    session = Session(Response(payload))
    client = Only1ApiClient("https://api.example.test", session=session)

    assert client.get_portfolio_recommendations() == payload
    assert session.calls[0][1] == "https://api.example.test/recommendations/portfolio"
    malformed = Only1ApiClient(
        "https://api.example.test",
        session=Session(Response({"advisory_only": False, "recommendations": []})),
    )
    with pytest.raises(DashboardApiError, match="invalid market recommendations"):
        malformed.get_portfolio_recommendations()


def test_recommendation_history_client_handles_empty_and_detail_contracts():
    empty_session = Session(Response({"records": [], "count": 0}))
    client = Only1ApiClient("https://api.example.test", session=empty_session)
    assert client.get_recommendation_history(limit=25) == []
    assert empty_session.calls[0][1].endswith("/recommendations/history")
    assert empty_session.calls[0][2]["params"] == {"limit": 25}

    detail = {"id": "history-1", "outcome": {"status": "no_action_taken"}}
    detail_client = Only1ApiClient(
        "https://api.example.test", session=Session(Response(detail))
    )
    assert detail_client.get_recommendation_history_detail("history-1") == detail

    analytics = {"sample_size": 0, "accuracy_available": False}
    analytics_client = Only1ApiClient(
        "https://api.example.test", session=Session(Response(analytics))
    )
    assert analytics_client.get_recommendation_history_analytics() == analytics


def test_recommendation_write_client_is_explicit_and_server_side(monkeypatch):
    disabled = Only1ApiClient("https://api.example.test", session=Session())
    assert disabled.recommendation_writes_configured is False
    with pytest.raises(DashboardApiError, match="authentication is required") as caught:
        disabled.capture_recommendation("BAT-001")
    assert caught.value.code == "authentication_required"

    session = Session(Response({"capture_status": "captured", "recommendation": {"id": "history-1"}}))
    client = Only1ApiClient(
        "https://api.example.test", session=session,
        operator_access_token="signed-oidc-token",
    )
    result = client.capture_recommendation("BAT-001")
    assert result["capture_status"] == "captured"
    method, url, kwargs = session.calls[0]
    assert method == "post"
    assert url.endswith("/recommendations/BAT-001/capture")
    assert kwargs["headers"] == {"Authorization": "Bearer signed-oidc-token"}


@pytest.mark.parametrize("action", ["acknowledge", "simulation", "dispatch"])
def test_recommendation_actions_submit_stable_ids(action):
    session = Session(Response({"id": "history-1"}))
    client = Only1ApiClient(
        "https://api.example.test", session=session,
        operator_access_token="signed-oidc-token",
    )
    if action == "acknowledge":
        client.acknowledge_recommendation("history-1", "Reviewed")
        assert session.calls[0][2]["json"] == {"note": "Reviewed"}
    elif action == "simulation":
        client.link_recommendation_simulation("history-1", "simulation-uuid")
        assert session.calls[0][2]["json"] == {"record_id": "simulation-uuid"}
    else:
        client.link_recommendation_dispatch("history-1", "dispatch-uuid")
        assert session.calls[0][2]["json"] == {"record_id": "dispatch-uuid"}


def test_recommendation_candidate_clients_are_api_backed():
    simulation_session = Session(Response([{"id": "simulation-uuid"}]))
    simulation_client = Only1ApiClient("https://api.example.test", session=simulation_session)
    assert simulation_client.get_simulations(asset_id="BAT-001") == [{"id": "simulation-uuid"}]
    assert simulation_session.calls[0][1].endswith("/simulations")
    assert simulation_session.calls[0][2]["params"]["asset_id"] == "BAT-001"

    dispatch_session = Session(Response([{"id": "dispatch-uuid"}]))
    dispatch_client = Only1ApiClient("https://api.example.test", session=dispatch_session)
    assert dispatch_client.get_dispatch_events(asset_id="BAT-001") == [{"id": "dispatch-uuid"}]
    assert dispatch_session.calls[0][1].endswith("/dispatch-events")


@pytest.mark.parametrize(
    ("error", "code"),
    [(requests.Timeout(), "timeout"), (requests.ConnectionError(), "connection_error")],
)
def test_summary_client_handles_transport_failures(error, code):
    client = Only1ApiClient(
        "https://api.example.test", session=Session(error=error)
    )
    with pytest.raises(DashboardApiError) as caught:
        client.get_portfolio_summary()
    assert caught.value.code == code


def test_summary_client_handles_safe_http_and_malformed_responses():
    rejected = Only1ApiClient(
        "https://api.example.test",
        session=Session(Response({"error_code": "invalid_timezone", "message": "Bad timezone"}, 400)),
    )
    with pytest.raises(DashboardApiError, match="Bad timezone") as caught:
        rejected.get_portfolio_summary()
    assert caught.value.code == "invalid_timezone"

    malformed = Only1ApiClient(
        "https://api.example.test", session=Session(Response({"portfolio": {}}))
    )
    with pytest.raises(DashboardApiError) as caught:
        malformed.get_portfolio_summary()
    assert caught.value.code == "invalid_response"


def test_summary_client_does_not_expose_server_error_details():
    client = Only1ApiClient(
        "https://api.example.test",
        session=Session(Response({
            "error_code": "supabase_unavailable",
            "message": "internal SQL and service-role-secret",
        }, 502)),
    )
    with pytest.raises(DashboardApiError) as caught:
        client.get_portfolio_summary()
    assert caught.value.code == "supabase_unavailable"
    assert "SQL" not in str(caught.value)
    assert "service-role" not in str(caught.value)

    unreadable = Only1ApiClient(
        "https://api.example.test", session=Session(Response(invalid_json=True))
    )
    with pytest.raises(DashboardApiError) as caught:
        unreadable.get_portfolio_summary()
    assert caught.value.code == "invalid_response"


def test_decimal_safe_value_formatting():
    assert format_currency("12450.25") == "$12,450.25"
    assert format_currency("-1220.5") == "-$1,220.50"
    assert format_currency(0) == "$0.00"
    assert format_currency(Decimal("123456789.99")) == "$123,456,789.99"
    assert format_energy("1245.3") == "1,245.30 MWh"
    assert format_power("10") == "10.00 MW"
    assert format_spread("42.17") == "$42.17/MWh"
    assert format_trading_return("0.25") == "25.00%"


def test_timestamp_formatting_converts_reporting_timezone_and_handles_null():
    assert format_timestamp(None, "America/Los_Angeles") == "Not available"
    assert format_timestamp(
        "2026-07-15T18:00:00Z", "America/Los_Angeles"
    ) == "Jul 15, 2026 · 11:00 AM PDT"


def test_date_formatting_matches_dashboard_labels():
    assert format_date("2026-07-11") == "Jul 11, 2026"
    assert format_date(None) == "Not available"


def test_chart_time_tick_only_shows_date_at_midnight():
    assert format_chart_time_tick(
        "2026-07-17T00:00:00-07:00", "America/Los_Angeles"
    ) == "12:00 AM<br>Jul 17, 2026"
    assert format_chart_time_tick(
        "2026-07-17T02:00:00-07:00", "America/Los_Angeles"
    ) == "2:00 AM"


def test_dispatch_timestamp_is_compact_and_omits_seconds():
    assert format_dispatch_timestamp(
        "2026-07-11T14:30:00Z", "America/Los_Angeles"
    ) == "Jul 11, 2026 · 7:30 AM PDT"
    assert format_dispatch_timestamp(None, "America/Los_Angeles") == "Not available"


def test_custom_range_is_timezone_aware_and_validated():
    start, end = custom_date_range(
        date(2026, 7, 1), date(2026, 7, 2), "America/Los_Angeles"
    )
    assert start.isoformat() == "2026-07-01T00:00:00-07:00"
    assert end.isoformat() == "2026-07-02T23:59:59.999999-07:00"
    with pytest.raises(DashboardStateError, match="on or after"):
        custom_date_range(date(2026, 7, 2), date(2026, 7, 1), "UTC")


def test_empty_summary_is_valid_state():
    empty = summary()
    empty["operations"]["total_dispatches"] = 0
    empty["fleet"]["active_assets"] = 0
    assert is_empty_summary(empty)
    assert not is_empty_summary(summary())


def test_pubba_api_base_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("PUBBA_POWER_API_BASE_URL", " https://api.pubbapower.com/ ")
    monkeypatch.setenv("ONLY1_API_BASE_URL", "https://legacy.example.test")

    client = Only1ApiClient()

    assert client.base_url == "https://api.pubbapower.com"


def test_legacy_api_base_url_remains_a_fallback(monkeypatch):
    monkeypatch.delenv("PUBBA_POWER_API_BASE_URL", raising=False)
    monkeypatch.setenv("ONLY1_API_BASE_URL", "https://legacy.example.test/")

    client = Only1ApiClient()

    assert client.base_url == "https://legacy.example.test"


def test_explicit_local_api_url_remains_supported(monkeypatch):
    monkeypatch.delenv("PUBBA_POWER_API_BASE_URL", raising=False)
    monkeypatch.delenv("ONLY1_API_BASE_URL", raising=False)

    assert Only1ApiClient("http://localhost:8000/").base_url == "http://localhost:8000"


def test_client_configuration_is_required(monkeypatch):
    monkeypatch.delenv("PUBBA_POWER_API_BASE_URL", raising=False)
    monkeypatch.delenv("ONLY1_API_BASE_URL", raising=False)
    with pytest.raises(DashboardApiError, match="PUBBA_POWER_API_BASE_URL"):
        Only1ApiClient()


def test_dashboard_module_import_does_not_make_network_call(monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("dashboard import performed a network request")

    monkeypatch.setattr(requests, "request", unexpected_request)
    import dashboard.app

    assert callable(dashboard.app.main)


def test_operator_workflow_has_no_direct_supabase_or_automatic_actions():
    dashboard_files = list(Path("dashboard").rglob("*.py"))
    source = "\n".join(path.read_text() for path in dashboard_files)
    assert "from supabase import" not in source
    assert "import supabase" not in source
    overview = Path("dashboard/pages/overview.py").read_text()
    history = Path("dashboard/pages/recommendation_history.py").read_text()
    assert overview.index("client.capture_recommendation") > overview.index("Confirm Capture")
    assert history.index("client.link_recommendation_simulation") > history.index("Link Existing Simulation")
    assert history.index("client.link_recommendation_dispatch") > history.index("Link Existing Dispatch")
    assert "autonomous" not in overview.lower()


def test_recommendation_history_page_renders_empty_state(monkeypatch):
    from dashboard.pages import recommendation_history

    monkeypatch.setattr(recommendation_history, "render_page_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(recommendation_history, "render_section_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(recommendation_history, "render_summary_grid", lambda *args, **kwargs: None)

    class St:
        captions = []
        infos = []
        def caption(self, value): self.captions.append(value)
        def info(self, value): self.infos.append(value)
        def warning(self, value): raise AssertionError(value)
        def columns(self, count): return [self] * count
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def selectbox(self, label, options, **kwargs): return options[0]
        def number_input(self, *args, **kwargs): return kwargs.get("value", 0)
        def checkbox(self, *args, **kwargs): return False

    class Client:
        def get_portfolio_assets(self): return []
        def get_recommendation_history(self, **kwargs): return []
        def get_recommendation_history_analytics(self):
            return {"sample_size": 0, "accuracy_message": "Insufficient history"}

    st = St()
    recommendation_history.render(st, Client())
    assert st.infos == ["No recommendations have been explicitly captured for these filters."]
    assert "Insufficient history" in st.captions
