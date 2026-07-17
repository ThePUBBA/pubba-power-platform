"""Enterprise live executive operations dashboard."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import floor
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from dashboard.charts import (
    CHART_CONFIG,
    GRAY,
    GRID,
    MINT,
    WHITE,
    daily_energy_figure,
    daily_financial_figure,
    dispatch_economics_figure,
    style_chart,
)
from dashboard.components import (
    render_capabilities,
    render_data_freshness,
    render_error_state,
    render_kpi_card,
    render_page_header,
    render_refresh_countdown,
    render_section_header,
    render_summary_grid,
    render_system_status,
)
from dashboard.formatting import (
    as_decimal,
    format_chart_time_tick,
    format_currency,
    format_date,
    format_dispatch_axis_label,
    format_dispatch_timestamp,
    format_energy,
    format_power,
    format_timestamp,
)
from dashboard.refresh import refresh_dashboard_data


def _tone(value: object) -> str:
    number = as_decimal(value)
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _numeric(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(as_decimal(value))
    except ValueError:
        return None


def _margin(profit: float, revenue: float) -> float | None:
    return profit / revenue if revenue else None


def _percent_label(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.1%}"


def _daily_dispatch_metrics(dispatches: list[dict], zone: str) -> list[dict]:
    """Aggregate complete returned dispatch values into honest reporting-day rows."""
    grouped: dict[str, dict] = {}
    required = (
        "revenue", "charging_cost", "profit",
        "charge_energy_mwh", "discharge_energy_mwh",
    )
    for dispatch in dispatches:
        timestamp = dispatch.get("timestamp")
        values = {field: _numeric(dispatch.get(field)) for field in required}
        if not timestamp or any(value is None for value in values.values()):
            continue
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            date_key = parsed.astimezone(ZoneInfo(zone)).date().isoformat()
        except (TypeError, ValueError):
            continue
        row = grouped.setdefault(date_key, {
            "date": date_key,
            "label": format_date(date_key),
            "revenue": 0.0,
            "charging_cost": 0.0,
            "profit": 0.0,
            "charge_energy_mwh": 0.0,
            "discharge_energy_mwh": 0.0,
            "dispatches": 0,
        })
        for field, value in values.items():
            row[field] += value
        row["dispatches"] += 1
    rows = [grouped[key] for key in sorted(grouped)]
    for row in rows:
        row["profit_margin"] = _margin(row["profit"], row["revenue"])
        row["profit_margin_label"] = _percent_label(row["profit_margin"])
        row["efficiency"] = (
            row["discharge_energy_mwh"] / row["charge_energy_mwh"]
            if row["charge_energy_mwh"] > 0 else None
        )
        row["efficiency_label"] = _percent_label(row["efficiency"])
    return rows


def _dispatch_chart_rows(dispatches: list[dict], zone: str) -> list[dict]:
    required = (
        "revenue", "charging_cost", "profit",
        "charge_energy_mwh", "discharge_energy_mwh",
    )
    complete = []
    for dispatch in sorted(dispatches, key=lambda row: str(row.get("timestamp") or "")):
        values = {field: _numeric(dispatch.get(field)) for field in required}
        if not dispatch.get("timestamp") or any(value is None for value in values.values()):
            continue
        classification_key = str(dispatch.get("data_quality") or "not_recorded")
        complete.append({
            **values,
            "timestamp": dispatch["timestamp"],
            "timestamp_label": format_dispatch_timestamp(dispatch["timestamp"], zone),
            "base_label": format_dispatch_axis_label(dispatch["timestamp"], zone),
            "asset": dispatch.get("asset_id") or "Unassigned",
            "market": dispatch.get("market") or "Not recorded",
            "node": dispatch.get("location") or "Not recorded",
            "classification_key": classification_key,
            "classification": classification_key.replace("_", " ").title(),
        })
    totals: dict[str, int] = {}
    for row in complete:
        totals[row["base_label"]] = totals.get(row["base_label"], 0) + 1
    seen: dict[str, int] = {}
    for row in complete:
        base = row["base_label"]
        seen[base] = seen.get(base, 0) + 1
        row["label"] = f"{base} · #{seen[base]}" if totals[base] > 1 else base
        row["profit_margin"] = _margin(row["profit"], row["revenue"])
        row["profit_margin_label"] = _percent_label(row["profit_margin"])
    return complete


def _market_day_axis(prices: list[dict], zone: str) -> tuple[list[str], list[str]]:
    """Return midnight through two hours beyond the latest market interval."""
    latest = datetime.fromisoformat(str(prices[-1]["timestamp"]).replace("Z", "+00:00"))
    latest_local = latest.astimezone(ZoneInfo(zone))
    local_day = latest_local.date()
    start = datetime.combine(local_day, time.min, tzinfo=ZoneInfo(zone))
    midnight = start + timedelta(days=1)
    end = min(latest_local + timedelta(hours=2), midnight)
    ticks = [
        (start + timedelta(hours=hour)).isoformat()
        for hour in range(0, 24, 2)
        if start + timedelta(hours=hour) <= end
    ]
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
    latest_timestamp = prices[-1]["timestamp"]
    latest_local = datetime.fromisoformat(
        str(latest_timestamp).replace("Z", "+00:00")
    ).astimezone(ZoneInfo(zone))
    label_on_left = latest_local.hour >= 21
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
        ticklabelstandoff=14,
        automargin=True,
        range=day_range,
    )
    upper_price = max(values)
    upper_axis = max(20, (floor(upper_price / 10) + 1) * 10)
    fig.update_yaxes(
        range=[9, upper_axis + 1],
        tick0=10,
        dtick=10,
        tickprefix="$",
        tickformat=",.0f",
    )
    fig.add_hline(y=10, line_color=GRID, line_width=1, layer="below")
    fig.add_hline(y=upper_axis, line_color=GRID, line_width=1, layer="below")
    fig.add_hline(y=current, line_dash="dot", line_color=GRAY)
    fig.add_annotation(
        x=latest_timestamp,
        y=current,
        text=f"Current ${current:,.2f}",
        showarrow=False,
        xanchor="right" if label_on_left else "left",
        yanchor="bottom",
        xshift=-12 if label_on_left else 12,
        yshift=10,
        font={"color": WHITE, "size": 12},
        bgcolor="#171717",
        bordercolor="#2A2A2A",
        borderpad=5,
    )
    fig = style_chart(
        fig, title="CAISO market price curve",
        subtitle=f"{metadata.get('market_name', 'CAISO')} · {metadata.get('market_type', 'RTM')} · {metadata.get('market_location')}",
        y_title=f"{currency}/MWh", height=430,
    )
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    st.caption(f"Latest interval {format_timestamp(metadata.get('market_updated_at'), zone)}")


def _performance_section(st, data: dict, currency: str, zone: str) -> None:
    render_section_header(st, "Portfolio Performance")
    dispatches = data["series"].get("dispatches", [])
    daily = _daily_dispatch_metrics(dispatches, zone)
    if not daily:
        st.info("Complete dispatch economics are required before portfolio performance can be displayed.")
        return
    total_revenue = sum(row["revenue"] for row in daily)
    total_cost = sum(row["charging_cost"] for row in daily)
    total_profit = sum(row["profit"] for row in daily)
    total_dispatches = sum(row["dispatches"] for row in daily)
    total_margin = _margin(total_profit, total_revenue)
    best_profit = max(daily, key=lambda row: row["profit"])
    best_revenue = max(daily, key=lambda row: row["revenue"])
    margin_rows = [row for row in daily if row["profit_margin"] is not None]
    best_margin = max(margin_rows, key=lambda row: row["profit_margin"]) if margin_rows else None
    lowest_profit = min(daily, key=lambda row: row["profit"])
    total_discharge = sum(row["discharge_energy_mwh"] for row in daily)
    render_summary_grid(st, [
        ("Total revenue", format_currency(total_revenue, currency)),
        ("Total charging cost", format_currency(total_cost, currency)),
        ("Total profit", format_currency(total_profit, currency)),
        ("Profit margin", _percent_label(total_margin)),
        ("Best-performing day", f'{best_profit["label"]} · {format_currency(best_profit["profit"], currency)}'),
        ("Average profit / dispatch", format_currency(total_profit / total_dispatches, currency)),
    ])
    financial = style_chart(
        daily_financial_figure(daily),
        title="Daily financial performance",
        subtitle="Gross revenue, charging cost, and retained profit from completed dispatch records.",
        y_title=f"{currency} ($)",
        height=440,
    )
    st.plotly_chart(financial, width="stretch", config=CHART_CONFIG)
    margin_text = (
        f'{best_margin["label"]} at {_percent_label(best_margin["profit_margin"])}'
        if best_margin else "Not available"
    )
    st.caption(
        f'Highest revenue · {best_revenue["label"]} ({format_currency(best_revenue["revenue"], currency)})'
        f' · Lowest profit · {lowest_profit["label"]} ({format_currency(lowest_profit["profit"], currency)})'
        f' · Best profit margin · {margin_text}'
    )
    energy = style_chart(
        daily_energy_figure(daily),
        title="Daily energy movement",
        subtitle="Charge and discharge energy by reporting date; energy ratio equals discharge divided by charge.",
        y_title="MWh",
        height=420,
    )
    st.plotly_chart(energy, width="stretch", config=CHART_CONFIG)
    st.caption(
        f"Total completed dispatches · {total_dispatches:,}"
        f" · Total discharged energy · {total_discharge:,.2f} MWh"
    )


def _dispatch_section(st, data: dict, currency: str, zone: str) -> None:
    render_section_header(st, "Dispatch Activity")
    dispatches = data["series"].get("dispatches", [])
    if not dispatches:
        st.info("No completed operational or simulation-derived dispatch records are available.")
        return
    chart_rows = _dispatch_chart_rows(dispatches, zone)
    if chart_rows:
        classifications = sorted({row["classification"] for row in chart_rows})
        dispatch_chart = style_chart(
            dispatch_economics_figure(chart_rows),
            title="Dispatch economics",
            subtitle="Revenue, charging cost, and retained profit for each completed dispatch.",
            y_title=f"{currency} ($)",
            height=460,
        )
        st.plotly_chart(dispatch_chart, width="stretch", config=CHART_CONFIG)
        best = max(chart_rows, key=lambda row: row["profit"])
        st.caption(
            f'Best dispatch · {best["label"]} ({format_currency(best["profit"], currency)} profit)'
            f' · Classification shown by hatch pattern and hover detail · {", ".join(classifications)}'
        )
    else:
        st.info("Complete dispatch economics are unavailable for charting; records remain in the table below.")
    rows = [{
        "Time": format_dispatch_timestamp(row.get("timestamp"), zone),
        "Asset": row.get("asset_id") or "Unassigned",
        "Charge MWh": _numeric(row.get("charge_energy_mwh")),
        "Discharge MWh": _numeric(row.get("discharge_energy_mwh")),
        "Revenue": _numeric(row.get("revenue")),
        "Charging Cost": _numeric(row.get("charging_cost")),
        "Profit": _numeric(row.get("profit")),
        "Profit Margin": _margin(
            _numeric(row.get("profit")) or 0,
            _numeric(row.get("revenue")) or 0,
        ),
        "Market": row.get("market") or "Not recorded",
        "Node": row.get("location") or "Not recorded",
        "Classification": str(row.get("data_quality", "")).replace("_", " ").title(),
    } for row in reversed(dispatches[-10:])]
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        column_config={
            "Time": st.column_config.TextColumn(width="medium"),
            "Asset": st.column_config.TextColumn(width="medium"),
            "Charge MWh": st.column_config.NumberColumn(format="%.2f MWh"),
            "Discharge MWh": st.column_config.NumberColumn(format="%.2f MWh"),
            "Revenue": st.column_config.NumberColumn(format="$%.2f"),
            "Charging Cost": st.column_config.NumberColumn(format="$%.2f"),
            "Profit": st.column_config.NumberColumn(format="$%.2f"),
            "Profit Margin": st.column_config.NumberColumn(format="percent"),
            "Node": st.column_config.TextColumn(width="large"),
            "Classification": st.column_config.TextColumn(width="medium"),
        },
    )


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
        {"label": "Last API Sync", "value": format_timestamp(kpis["last_api_sync_at"], zone), "subtitle": f"Request latency · {payload['latency_ms']:.0f} ms", "icon": "◷", "tone": "positive"},
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
    _performance_section(st, data, currency, zone)
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
