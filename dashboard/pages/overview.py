"""Enterprise live executive operations dashboard."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from dashboard.charts import GRAY, MINT, WHITE, style_chart, trend_figure
from dashboard.components import (
    render_capabilities,
    render_data_freshness,
    render_error_state,
    render_kpi_card,
    render_page_header,
    render_refresh_countdown,
    render_section_header,
    render_system_status,
)
from dashboard.formatting import (
    as_decimal,
    format_chart_time_tick,
    format_currency,
    format_date,
    format_dispatch_timestamp,
    format_energy,
    format_power,
    format_timestamp,
)
from dashboard.refresh import refresh_dashboard_data


def _tone(value: object) -> str:
    number = as_decimal(value)
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _market_day_axis(prices: list[dict], zone: str) -> tuple[list[str], list[str]]:
    """Return the full local trading-day range and two-hour tick positions."""
    latest = datetime.fromisoformat(str(prices[-1]["timestamp"]).replace("Z", "+00:00"))
    local_day = latest.astimezone(ZoneInfo(zone)).date()
    start = datetime.combine(local_day, time.min, tzinfo=ZoneInfo(zone))
    end = start + timedelta(days=1)
    ticks = [(start + timedelta(hours=hour)).isoformat() for hour in range(0, 24, 2)]
    return [start.isoformat(), end.isoformat()], ticks


def _cards(st, cards: list[dict]) -> None:
    for start in range(0, len(cards), 3):
        columns = st.columns(3)
        for column, card in zip(columns, cards[start:start + 3]):
            with column:
                render_kpi_card(st, **card)


def _market_section(st, data: dict, currency: str, zone: str) -> None:
    render_section_header(st, "Market Intelligence")
    prices = data["series"].get("market_prices", [])
    metadata = data["metadata"]
    stats = metadata.get("market_statistics", {})
    snapshot = [
        ("Current", data["kpis"].get("current_market_price_per_mwh")),
        ("Minimum", stats.get("minimum_price_per_mwh")),
        ("Maximum", stats.get("maximum_price_per_mwh")),
        ("Average", stats.get("average_price_per_mwh")),
        ("Spread", stats.get("price_spread_per_mwh")),
    ]
    cols = st.columns(5)
    for col, (label, value) in zip(cols, snapshot):
        with col:
            render_kpi_card(
                st, label, "Not available" if value is None else f"{format_currency(value, currency)}/MWh",
                subtitle=f"{metadata.get('market_type', 'RTM')} · {metadata.get('market_location', 'Unknown node')}",
                tone="neutral", icon="↗",
            )
    if not prices:
        st.info("CAISO market data is unavailable. No price is inferred or presented as live.")
        return
    values = [point["price_per_mwh"] for point in prices]
    market_times = [format_timestamp(point["timestamp"], zone) for point in prices]
    day_range, tick_values = _market_day_axis(prices, zone)
    fig = go.Figure(go.Scatter(
        x=[point["timestamp"] for point in prices], y=values,
        customdata=market_times,
        line={"color": MINT, "width": 3}, name="CAISO RTM LMP",
        hovertemplate="%{customdata}<br>$%{y:,.2f}/MWh<extra></extra>",
    ))
    current = values[-1]
    fig.update_xaxes(
        type="date",
        tickmode="array",
        tickvals=tick_values,
        ticktext=[format_chart_time_tick(value, zone) for value in tick_values],
        tickangle=0,
        automargin=True,
        range=day_range,
    )
    fig.add_hline(y=current, line_dash="dot", line_color=GRAY)
    fig = style_chart(
        fig, title="CAISO market price curve",
        subtitle=f"{metadata.get('market_name', 'CAISO')} · {metadata.get('market_type', 'RTM')} · {metadata.get('market_location')}",
        y_title=f"{currency}/MWh", height=430,
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Latest interval {format_timestamp(metadata.get('market_updated_at'), zone)}")


def _performance_section(st, data: dict, currency: str) -> None:
    render_section_header(st, "Portfolio Performance")
    daily = data["series"].get("daily", [])
    if not daily:
        st.info("Completed dispatch history is required before portfolio performance trends can be displayed.")
        return
    chart_daily = [{**row, "date": format_date(row.get("date"))} for row in daily]
    left, right = st.columns(2)
    one_point = len(daily) == 1
    note = "Single reporting date; additional dispatch history will create a trend." if one_point else "Completed dispatch ledger by reporting date."
    with left:
        fig = trend_figure(chart_daily, "revenue", name="Revenue", color=MINT, currency=True)
        st.plotly_chart(style_chart(fig, title="Revenue over time", subtitle=note, y_title=f"{currency} ($)"), width="stretch")
    with right:
        fig = trend_figure(chart_daily, "profit", name="Profit", color=WHITE, currency=True)
        st.plotly_chart(style_chart(fig, title="Profit over time", subtitle=note, y_title=f"{currency} ($)"), width="stretch")
    fig = go.Figure(go.Bar(
        x=[row["date"] for row in chart_daily], y=[row["throughput_mwh"] for row in chart_daily],
        marker_color=MINT, name="Throughput", hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
    ))
    if one_point:
        fig.update_xaxes(type="category")
    st.plotly_chart(style_chart(fig, title="Daily energy throughput", subtitle=note, y_title="MWh"), width="stretch")


def _dispatch_section(st, data: dict, currency: str, zone: str) -> None:
    render_section_header(st, "Dispatch Activity")
    dispatches = data["series"].get("dispatches", [])
    if not dispatches:
        st.info("No completed operational or simulation-derived dispatch records are available.")
        return
    display_times = [format_dispatch_timestamp(row.get("timestamp"), zone) for row in dispatches]
    fig = go.Figure(go.Scatter(
        x=display_times, y=[row["discharge_energy_mwh"] for row in dispatches],
        mode="markers", marker={"color": MINT, "size": 11}, name="Dispatch",
        customdata=[[display_time, row.get("asset_id"), row.get("profit"), row.get("data_quality")] for display_time, row in zip(display_times, dispatches)],
        hovertemplate="%{customdata[0]}<br>%{y:,.2f} MWh<br>Asset %{customdata[1]}<br>Profit $%{customdata[2]:,.2f}<br>%{customdata[3]}<extra></extra>",
    ))
    fig.update_xaxes(type="category")
    st.plotly_chart(style_chart(fig, title="Dispatch timeline", subtitle="Completed ledger events; simulated records remain explicitly classified.", y_title="Discharged MWh"), width="stretch")
    rows = [{
        "Time": format_dispatch_timestamp(row.get("timestamp"), zone),
        "Asset": row.get("asset_id") or "Unassigned",
        "Charge MWh": float(row.get("charge_energy_mwh") or 0),
        "Discharge MWh": float(row.get("discharge_energy_mwh") or 0),
        "Revenue": format_currency(row.get("revenue"), currency),
        "Charging Cost": format_currency(row.get("charging_cost"), currency),
        "Profit": format_currency(row.get("profit"), currency),
        "Market": row.get("market") or "Not recorded",
        "Node": row.get("location") or "Not recorded",
        "Classification": str(row.get("data_quality", "")).replace("_", " ").title(),
    } for row in reversed(dispatches[-10:])]
    st.dataframe(rows, width="stretch", hide_index=True)


def _assets_section(st, payload: dict, currency: str, zone: str) -> None:
    render_section_header(st, "Asset Intelligence")
    assets = payload.get("assets", [])
    if not assets:
        st.info("No active asset intelligence is available through the portfolio API.")
        return
    rows = [{
        "Asset": item.get("asset_name") or item.get("asset_id"),
        "Technology": item.get("technology") or "Not recorded",
        "Location": item.get("location") or "Not recorded",
        "Status": item.get("status") or "Unknown",
        "Power": format_power(item.get("power_mw")),
        "Energy": format_energy(item.get("energy_mwh")),
        "Dispatches": int(item.get("total_dispatches") or 0),
        "Revenue": format_currency(item.get("total_revenue"), currency),
        "Profit": format_currency(item.get("total_profit"), currency),
        "Last Dispatch": format_timestamp(item.get("last_dispatch_time"), zone),
    } for item in assets]
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_live(st, client) -> None:
    control, action = st.columns([5, 1])
    with control:
        timezone_name = st.text_input("Reporting timezone", placeholder="Use portfolio default", help="Optional IANA timezone such as America/Denver.")
    with action:
        st.write("")
        st.button("Refresh", type="primary", width="stretch", help="Request fresh API, Supabase, and CAISO data now.")
    render_refresh_countdown(st)
    with st.spinner("Refreshing live operations data…"):
        payload, error = refresh_dashboard_data(st.session_state, client, timezone_name=timezone_name or None)
    if error:
        if payload:
            st.warning(f"Live refresh failed — {error} Previously loaded successful data remains visible.")
        else:
            render_error_state(st, error)
            return
    data = payload["dashboard"]
    zone = data["period"]["timezone"]
    currency = data["portfolio"]["currency_code"]
    kpis = data["kpis"]
    metadata = data["metadata"]
    refreshed_at = payload["refreshed_at"]
    render_page_header(st, "Executive Operations", "Live portfolio economics, fleet capacity, dispatch activity, and CAISO market intelligence.", badge="Live data", environment="Production")
    st.caption(f"Last successful refresh {format_timestamp(refreshed_at, zone)} · Data freshness {format_timestamp(metadata.get('data_freshness_at'), zone)} · API latency {payload['latency_ms']:.0f} ms")

    render_section_header(st, "Executive Overview")
    _cards(st, [
        {"label": "Portfolio Value", "value": "Not available", "subtitle": "Requires valuation integration", "icon": "◇", "tooltip": "No authoritative valuation source is connected."},
        {"label": "Today's Revenue", "value": format_currency(kpis["today_revenue"], currency), "subtitle": "Completed dispatch ledger", "icon": "$", "tone": _tone(kpis["today_revenue"])},
        {"label": "Today's Profit", "value": format_currency(kpis["today_profit"], currency), "subtitle": data["data_quality"]["financial_values"].replace("_", " ").title(), "icon": "↗", "tone": _tone(kpis["today_profit"])},
        {"label": "Available Capacity", "value": format_power(kpis["available_capacity_mw"]), "subtitle": "Configured active assets", "icon": "⚡"},
        {"label": "Active Assets", "value": f'{kpis["active_assets"]:,}', "subtitle": "Portfolio fleet", "icon": "▦"},
        {"label": "Today's Dispatches", "value": f'{kpis["today_dispatches"]:,}', "subtitle": f"Reporting timezone · {zone}", "icon": "↔"},
        {"label": "Battery State of Charge", "value": "Not available", "subtitle": "Requires telemetry integration", "icon": "▤"},
        {"label": "Current Market Price", "value": "Not available" if kpis["current_market_price_per_mwh"] is None else f'{format_currency(kpis["current_market_price_per_mwh"], currency)}/MWh', "subtitle": f'{metadata.get("market_type", "RTM")} · {metadata.get("market_location")}', "icon": "⌁"},
        {"label": "Last API Sync", "value": format_timestamp(kpis["last_api_sync_at"], zone), "subtitle": f"Request latency · {payload['latency_ms']:.0f} ms", "icon": "◷", "tone": "neutral"},
    ])

    render_section_header(st, "System Health")
    checked = format_timestamp(refreshed_at, zone)
    status = data["status"]
    render_system_status(st, [
        ("API", status["api"].title(), status["api"] == "connected", f"Checked {checked} · {payload['latency_ms']:.0f} ms total request latency"),
        ("Supabase", status["supabase"].title(), status["supabase"] == "connected", f"Ledger aggregation checked {checked}"),
        ("CAISO Market Data", status["market_data"].replace("_", " ").title(), status["market_data"] == "connected", f"Latest interval {format_timestamp(metadata.get('market_updated_at'), zone)}"),
        ("Simulation Engine", status["simulation_engine"].title(), status["simulation_engine"] == "ready", "Historical calculation workflow available"),
    ])
    render_data_freshness(st, format_timestamp(metadata.get("data_freshness_at"), zone))
    _market_section(st, data, currency, zone)
    _performance_section(st, data, currency)
    _dispatch_section(st, data, currency, zone)
    _assets_section(st, payload, currency, zone)

    render_section_header(st, "Future Capabilities")
    render_capabilities(st, [
        ("Battery Telemetry", "Will unlock live SOC, charge rate, temperature, alarms, and cycle tracking.", "Telemetry API"),
        ("Portfolio Valuation", "Will unlock asset value, project returns, and portfolio NAV.", "Financial valuation source"),
        ("Forecasting", "Will unlock price, load, and renewable generation outlooks.", "Forecast data service"),
        ("Asset Health", "Will unlock condition monitoring, alarms, and maintenance risk.", "OEM or SCADA data"),
        ("Fleet Optimization", "Will unlock coordinated multi-asset dispatch recommendations.", "Optimization engine"),
    ])


def render(st, client) -> None:
    # Streamlit fragments provide bounded 60-second reruns without re-running navigation.
    st.fragment(run_every=60)(_render_live)(st, client)
