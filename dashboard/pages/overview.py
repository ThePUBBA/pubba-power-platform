"""Live executive Overview Streamlit page."""

from __future__ import annotations

from decimal import Decimal

import plotly.graph_objects as go

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import (
    render_data_freshness,
    render_error_state,
    render_kpi_card,
    render_page_header,
    render_section_header,
    render_system_status,
)
from dashboard.formatting import (
    as_decimal,
    format_currency,
    format_power,
    format_timestamp,
)


MINT = "#44FFBB"
WHITE = "#FFFFFF"
MUTED = "#A7A7A7"
GRID = "#2A2A2A"


def _tone(value: object) -> str:
    number = as_decimal(value)
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _available(value: object, formatter) -> str:
    return "Not available" if value is None else formatter(value)


def _cards(st, cards: list[tuple[str, str, str]], columns: int = 3) -> None:
    for start in range(0, len(cards), columns):
        row = st.columns(columns)
        for column, (label, value, tone) in zip(row, cards[start:start + columns]):
            with column:
                render_kpi_card(st, label, value, tone=tone)


def _layout(fig: go.Figure, title: str, y_title: str = "") -> go.Figure:
    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": WHITE, "family": "Inter, Arial, sans-serif"},
        margin={"l": 45, "r": 20, "t": 55, "b": 40},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=y_title)
    return fig


def _empty_chart(st, title: str, message: str) -> None:
    render_section_header(st, title)
    st.info(message)


def render(st, client: Only1ApiClient) -> None:
    render_page_header(
        st,
        "Executive Operations",
        "Live portfolio economics, dispatch activity, fleet capacity, and market intelligence.",
        badge="Live data",
    )
    toolbar, refresh = st.columns([5, 1])
    with toolbar:
        timezone_name = st.text_input(
            "Dashboard timezone override",
            placeholder="Use portfolio default",
            help="Optional IANA timezone, for example America/Denver.",
        )
    with refresh:
        st.write("")
        st.button("Refresh", type="primary", width="stretch")

    try:
        with st.spinner("Loading live executive data…"):
            data = client.get_dashboard_summary(timezone_name=timezone_name or None)
    except DashboardApiError as exc:
        render_error_state(st, str(exc))
        return

    kpis = data["kpis"]
    series = data["series"]
    status = data["status"]
    metadata = data["metadata"]
    zone = data["period"]["timezone"]
    currency = data["portfolio"]["currency_code"]

    _cards(st, [
        ("Portfolio Value", "Not available", "neutral"),
        ("Today's Revenue", format_currency(kpis["today_revenue"], currency), _tone(kpis["today_revenue"])),
        ("Today's Profit", format_currency(kpis["today_profit"], currency), _tone(kpis["today_profit"])),
        ("Available Capacity", format_power(kpis["available_capacity_mw"]), "neutral"),
        ("Active Assets", f'{kpis["active_assets"]:,}', "neutral"),
        ("Today's Dispatches", f'{kpis["today_dispatches"]:,}', "neutral"),
        ("Battery State of Charge", "Not available", "neutral"),
        ("Current Market Price", _available(kpis["current_market_price_per_mwh"], lambda value: f'{format_currency(value, currency)}/MWh'), "neutral"),
        ("Last API Sync", format_timestamp(kpis["last_api_sync_at"], zone), "positive"),
    ])
    quality = data["data_quality"]["financial_values"].replace("_", " ").title()
    st.caption(
        f"Financial ledger classification: {quality}. Available capacity is configured active-asset capacity. "
        "Portfolio valuation and battery SOC require sources that are not currently present."
    )

    render_section_header(st, "System status")
    render_system_status(st, [
        ("API", status["api"].replace("_", " ").title(), status["api"] == "connected"),
        ("Supabase", status["supabase"].replace("_", " ").title(), status["supabase"] == "connected"),
        ("CAISO Market Data", status["market_data"].replace("_", " ").title(), status["market_data"] == "connected"),
        ("Simulation Engine", status["simulation_engine"].replace("_", " ").title(), status["simulation_engine"] == "ready"),
    ])
    render_data_freshness(
        st,
        format_timestamp(metadata.get("data_freshness_at"), zone, fallback="No ledger updates"),
    )

    daily = series.get("daily", [])
    if daily:
        left, right = st.columns(2)
        with left:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=[row["date"] for row in daily], y=[row["revenue"] for row in daily], name="Revenue", line={"color": MINT, "width": 3}))
            st.plotly_chart(_layout(fig, "Revenue over time", currency), width="stretch")
        with right:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=[row["date"] for row in daily], y=[row["profit"] for row in daily], name="Profit", line={"color": WHITE, "width": 3}))
            st.plotly_chart(_layout(fig, "Profit over time", currency), width="stretch")

        left, right = st.columns(2)
        with left:
            fig = go.Figure(go.Bar(x=[row["date"] for row in daily], y=[row["throughput_mwh"] for row in daily], marker_color=MINT, name="Throughput"))
            st.plotly_chart(_layout(fig, "Daily energy throughput", "MWh"), width="stretch")
        with right:
            dispatches = series.get("dispatches", [])
            fig = go.Figure(go.Scatter(
                x=[row["timestamp"] for row in dispatches],
                y=[row["energy_mwh"] for row in dispatches],
                mode="markers", marker={"color": MINT, "size": 10}, name="Dispatch",
                text=[row.get("asset_id") or "Unassigned asset" for row in dispatches],
            ))
            st.plotly_chart(_layout(fig, "Dispatch timeline", "MWh"), width="stretch")
    else:
        _empty_chart(st, "Portfolio trends", "No completed dispatch records are available for revenue, profit, throughput, or dispatch charts.")

    prices = series.get("market_prices", [])
    if prices:
        fig = go.Figure(go.Scatter(x=[row["timestamp"] for row in prices], y=[row["price_per_mwh"] for row in prices], line={"color": MINT, "width": 3}, name="CAISO RTM LMP"))
        st.plotly_chart(_layout(fig, "CAISO market price curve", f"{currency}/MWh"), width="stretch")
    else:
        _empty_chart(st, "CAISO market price curve", "Live CAISO pricing is currently unavailable. No market prices are being inferred or cached as live values.")

    unavailable_a, unavailable_b = st.columns(2)
    with unavailable_a:
        _empty_chart(st, "Battery state of charge", "No state-of-charge telemetry or history is available through the backend yet.")
    with unavailable_b:
        _empty_chart(st, "Asset utilization", "No authoritative asset-availability hours are stored, so utilization is not estimated.")

    st.caption(
        f"Generated {format_timestamp(metadata['generated_at'], zone)} · "
        f"Ledger freshness {format_timestamp(metadata.get('data_freshness_at'), zone, fallback='Not available')} · "
        f"CAISO freshness {format_timestamp(metadata.get('market_updated_at'), zone, fallback='Not available')}"
    )
