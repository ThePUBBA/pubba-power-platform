"""Stateful refresh behavior that preserves the last successful live payload."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

    telemetry_history = []
    telemetry_error = None
    recommendation_error = None
    recommendations = dashboard.get("recommendations")
    series = dashboard.setdefault("series", {})
    if not series.get("previous_market_prices") and hasattr(client, "get_lmp_prices"):
        metadata = dashboard.get("metadata") or {}
        market_updated_at = metadata.get("market_updated_at")
        try:
            latest = datetime.fromisoformat(str(market_updated_at).replace("Z", "+00:00"))
            market_zone = ZoneInfo("America/Los_Angeles")
            previous_date = (latest.astimezone(market_zone).date() - timedelta(days=1)).isoformat()
            previous_rows = client.get_lmp_prices(
                location=str(metadata.get("market_location") or "TH_NP15_GEN-APND"),
                market=str(metadata.get("market_type") or "RTM"),
                date=previous_date,
            )
            series["previous_market_prices"] = [
                {
                    "timestamp": row.get("timestamp"),
                    "price_per_mwh": row.get("lmp_prc"),
                }
                for row in previous_rows
                if row.get("timestamp") and row.get("lmp_prc") is not None
            ]
            total_latency += client.last_latency_ms or 0.0
        except (DashboardApiError, TypeError, ValueError, ZoneInfoNotFoundError):
            series["previous_market_prices"] = []
    telemetry_assets = (dashboard.get("telemetry") or {}).get("assets") or []
    if telemetry_assets and hasattr(client, "get_telemetry_history"):
        try:
            telemetry_history = client.get_telemetry_history(
                str(telemetry_assets[0].get("asset_id") or "")
            )
            total_latency += client.last_latency_ms or 0.0
        except DashboardApiError as exc:
            telemetry_error = str(exc)
    if recommendations is None and hasattr(client, "get_portfolio_recommendations"):
        try:
            recommendations = client.get_portfolio_recommendations()
            total_latency += client.last_latency_ms or 0.0
        except DashboardApiError as exc:
            recommendation_error = str(exc)
    payload = {
        "dashboard": dashboard,
        "assets": assets,
        "telemetry_history": telemetry_history,
        "telemetry_error": telemetry_error,
        "recommendations": recommendations,
        "recommendation_error": recommendation_error,
        "latency_ms": total_latency,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    state[STATE_KEY] = {"data": payload}
    return payload, None
