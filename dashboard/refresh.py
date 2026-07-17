"""Stateful refresh behavior that preserves the last successful live payload."""

from __future__ import annotations

from datetime import datetime, timezone

from dashboard.api_client import DashboardApiError, Only1ApiClient


STATE_KEY = "pubba_live_dashboard"


def refresh_dashboard_data(
    state: dict,
    client: Only1ApiClient,
    *,
    timezone_name: str | None = None,
) -> tuple[dict | None, str | None]:
    try:
        dashboard = client.get_dashboard_summary(timezone_name=timezone_name)
        dashboard_latency = client.last_latency_ms or 0.0
        assets = client.get_portfolio_assets()
        total_latency = dashboard_latency + (client.last_latency_ms or 0.0)
    except DashboardApiError as exc:
        previous = state.get(STATE_KEY)
        return (previous.get("data") if previous else None), str(exc)

    payload = {
        "dashboard": dashboard,
        "assets": assets,
        "latency_ms": total_latency,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    state[STATE_KEY] = {"data": payload}
    return payload, None
