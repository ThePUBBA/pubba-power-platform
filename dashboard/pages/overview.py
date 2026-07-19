"""Enterprise live executive operations dashboard."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import floor
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from dashboard.api_client import DashboardApiError
from dashboard.auth import can
from dashboard.charts import (
    CHART_CONFIG,
    MINT,
    daily_energy_figure,
    daily_financial_figure,
    dispatch_economics_figure,
    chart_palette,
    style_chart,
    telemetry_history_figure,
)
from dashboard.components import (
    render_capabilities,
    render_asset_cards,
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
from dashboard.theme import THEMES


def _tone(value: object) -> str:
    number = as_decimal(value)
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _caption_text(value: str) -> str:
    """Prevent currency symbols from being parsed as inline math by Markdown."""
    return value.replace("$", r"\$")


def _numeric(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(as_decimal(value))
    except ValueError:
        return None


def _optional_power(value: object) -> str:
    return "Not available" if _numeric(value) is None else format_power(value)


def _optional_energy(value: object) -> str:
    return "Not available" if _numeric(value) is None else format_energy(value)


def _parsed_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _align_market_comparison(
    points: list[dict], *, comparison_date, zone: str,
) -> list[dict]:
    """Align another trade day's intervals to the current day's clock times."""
    aligned = []
    local_zone = ZoneInfo(zone)
    for point in points:
        stamp = _parsed_timestamp(point.get("timestamp")) if isinstance(point, dict) else None
        price = _numeric(point.get("price_per_mwh")) if isinstance(point, dict) else None
        if stamp is None or price is None:
            continue
        local = stamp.astimezone(local_zone)
        comparison_stamp = datetime.combine(
            comparison_date, local.time().replace(tzinfo=None), tzinfo=local_zone,
        )
        aligned.append({
            "timestamp": comparison_stamp.isoformat(),
            "price_per_mwh": price,
            "source_timestamp": point.get("timestamp"),
        })
    return sorted(aligned, key=lambda point: point["timestamp"])


def _margin(profit: float, revenue: float) -> float | None:
    return profit / revenue if revenue else None


def _percent_label(value: float | None) -> str:
    return "Not available" if value is None else f"{value:.1%}"


def _asset_presentation_mode(count: int) -> str:
    return "cards" if count <= 3 else "table"


def _selected_asset_id(assets: list[dict], selected: str | None = None) -> str | None:
    identifiers = [str(item.get("asset_id") or "") for item in assets if item.get("asset_id")]
    return selected if selected in identifiers else identifiers[0] if identifiers else None


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
        parsed = _parsed_timestamp(timestamp)
        if parsed is None:
            continue
        date_key = parsed.astimezone(ZoneInfo(zone)).date().isoformat()
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
        if _parsed_timestamp(dispatch.get("timestamp")) is None or any(value is None for value in values.values()):
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
    theme = str(st.session_state.get("pubba_theme_mode") or "dark")
    palette = chart_palette(theme)
    render_section_header(st, "Market Intelligence")
    raw_prices = (data.get("series") or {}).get("market_prices", [])
    raw_previous_prices = (data.get("series") or {}).get("previous_market_prices", [])
    prices = [
        {"timestamp": point.get("timestamp"), "price_per_mwh": _numeric(point.get("price_per_mwh"))}
        for point in raw_prices
        if isinstance(point, dict)
        and _parsed_timestamp(point.get("timestamp")) is not None
        and _numeric(point.get("price_per_mwh")) is not None
    ]
    metadata = data.get("metadata") or {}
    stats = metadata.get("market_statistics", {})
    snapshot = [
        ("Current", (data.get("kpis") or {}).get("current_market_price_per_mwh")),
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
    previous_prices = _align_market_comparison(
        raw_previous_prices,
        comparison_date=latest_local.date(),
        zone=zone,
    )
    label_on_left = latest_local.hour >= 21
    fig = go.Figure()
    if previous_prices:
        previous_source_date = _parsed_timestamp(
            previous_prices[0]["source_timestamp"]
        ).astimezone(ZoneInfo(zone))
        fig.add_trace(go.Scatter(
            x=[point["timestamp"] for point in previous_prices],
            y=[point["price_per_mwh"] for point in previous_prices],
            customdata=[
                format_timestamp(point["source_timestamp"], zone)
                for point in previous_prices
            ],
            line={"color": palette["neutral"], "width": 2, "dash": "dash"},
            name=f"Previous day · {previous_source_date.strftime('%b %-d')}",
            hovertemplate="Previous day<br>%{customdata}<br>$%{y:,.2f}/MWh<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=[point["timestamp"] for point in prices], y=values,
        customdata=market_times,
        line={"color": MINT, "width": 3}, name="Today",
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
    comparison_values = [point["price_per_mwh"] for point in previous_prices]
    visible_values = values + comparison_values
    lower_price = min(visible_values)
    upper_price = max(visible_values)
    lower_axis = min(0, floor(lower_price / 10) * 10)
    upper_axis = max(20, (floor(upper_price / 10) + 1) * 10)
    fig.update_yaxes(
        range=[lower_axis, upper_axis],
        tick0=0,
        dtick=10,
        tickprefix="$",
        tickformat=",.0f",
    )
    fig.add_hline(y=lower_axis, line_color=palette["grid"], line_width=1, layer="below")
    if lower_axis < 0:
        fig.add_hline(y=0, line_color=palette["neutral"], line_width=1, layer="below")
    fig.add_hline(y=upper_axis, line_color=palette["grid"], line_width=1, layer="below")
    fig.add_hline(y=current, line_dash="dot", line_color=palette["neutral"])
    fig.add_annotation(
        x=latest_timestamp,
        y=current,
        text=f"Current ${current:,.2f}",
        showarrow=False,
        xanchor="right" if label_on_left else "left",
        yanchor="bottom",
        xshift=-12 if label_on_left else 12,
        yshift=10,
        font={"color": palette["primary"], "size": 12},
        bgcolor=palette["surface"],
        bordercolor=palette["grid"],
        borderpad=5,
    )
    fig = style_chart(
        fig, title="CAISO market price curve",
        subtitle=f"{metadata.get('market_name', 'CAISO')} · {metadata.get('market_type', 'RTM')} · {metadata.get('market_location')}",
        y_title=f"{currency}/MWh", height=430, theme=theme,
    )
    fig.update_layout(hovermode="closest", showlegend=bool(previous_prices))
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    st.caption(f"Latest interval {format_timestamp(metadata.get('market_updated_at'), zone)}")


def _performance_section(st, data: dict, currency: str, zone: str) -> None:
    theme = str(st.session_state.get("pubba_theme_mode") or "dark")
    render_section_header(st, "Portfolio Performance")
    dispatches = (data.get("series") or {}).get("dispatches", [])
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
        daily_financial_figure(daily, theme=theme),
        title="Daily financial performance",
        subtitle="Gross revenue, charging cost, and retained profit from completed dispatch records.",
        y_title=f"{currency} ($)",
        height=440, theme=theme,
    )
    st.plotly_chart(financial, width="stretch", config=CHART_CONFIG)
    margin_text = (
        f'{best_margin["label"]} at {_percent_label(best_margin["profit_margin"])}'
        if best_margin else "Not available"
    )
    st.caption(_caption_text(
        f'Highest revenue · {best_revenue["label"]} ({format_currency(best_revenue["revenue"], currency)})'
        f' · Lowest profit · {lowest_profit["label"]} ({format_currency(lowest_profit["profit"], currency)})'
        f' · Best profit margin · {margin_text}'
    ))
    energy = style_chart(
        daily_energy_figure(daily, theme=theme),
        title="Daily energy movement",
        subtitle="Charge and discharge energy by reporting date; energy ratio equals discharge divided by charge.",
        y_title="MWh",
        height=420, theme=theme,
    )
    st.plotly_chart(energy, width="stretch", config=CHART_CONFIG)
    st.caption(
        f"Total completed dispatches · {total_dispatches:,}"
        f" · Total discharged energy · {total_discharge:,.2f} MWh"
    )


def _dispatch_section(st, data: dict, currency: str, zone: str) -> None:
    theme = str(st.session_state.get("pubba_theme_mode") or "dark")
    render_section_header(st, "Dispatch Economics")
    dispatches = (data.get("series") or {}).get("dispatches", [])
    if not dispatches:
        st.info("No completed operational or simulation-derived dispatch records are available.")
        return
    chart_rows = _dispatch_chart_rows(dispatches, zone)
    if chart_rows:
        classifications = sorted({row["classification"] for row in chart_rows})
        dispatch_chart = style_chart(
            dispatch_economics_figure(chart_rows, theme=theme),
            title="Dispatch economics",
            subtitle="Revenue, charging cost, and retained profit for each completed dispatch.",
            y_title=f"{currency} ($)",
            height=460, theme=theme,
        )
        st.plotly_chart(dispatch_chart, width="stretch", config=CHART_CONFIG)
        best = max(chart_rows, key=lambda row: row["profit"])
        st.caption(_caption_text(
            f'Best dispatch · {best["label"]} ({format_currency(best["profit"], currency)} profit)'
            f' · Classification shown by hatch pattern and hover detail · {", ".join(classifications)}'
        ))
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


def _assets_section(st, payload: dict, currency: str, zone: str, client) -> None:
    render_section_header(st, "Asset Intelligence")
    assets = payload.get("assets", [])
    if not assets:
        st.info("No active asset intelligence is available through the portfolio API.")
        return
    active = [item for item in assets if str(item.get("status", "")).lower() == "active"]
    total_power = sum(_numeric(item.get("power_mw")) or 0 for item in assets)
    total_energy = sum(_numeric(item.get("energy_mwh")) or 0 for item in assets)
    total_revenue = sum(_numeric(item.get("total_revenue")) or 0 for item in assets)
    total_profit = sum(_numeric(item.get("total_profit")) or 0 for item in assets)
    summary_items = [
        ("Portfolio assets", f"{len(assets):,}"),
        ("Active assets", f"{len(active):,}"),
        ("Total power", format_power(total_power)),
        ("Total energy", format_energy(total_energy)),
        ("Asset revenue", format_currency(total_revenue, currency)),
        ("Asset profit", format_currency(total_profit, currency)),
    ]
    telemetry = (payload.get("dashboard") or {}).get("telemetry") or {}
    telemetry_assets = {
        str(item.get("asset_id") or ""): item
        for item in telemetry.get("assets") or []
    }
    if telemetry.get("status") == "available":
        source = str(telemetry.get("source_classification") or "operational").title()
        summary_items.extend([
            ("Average SOC", f'{telemetry["average_state_of_charge_pct"]:.1f}%' if telemetry.get("average_state_of_charge_pct") is not None else "Not available"),
            ("Available charge", _optional_power(telemetry.get("total_available_charge_power_mw"))),
            ("Available discharge", _optional_power(telemetry.get("total_available_discharge_power_mw"))),
            ("Ready to charge", f'{telemetry.get("assets_ready_to_charge", 0):,}'),
            ("Ready to discharge", f'{telemetry.get("assets_ready_to_discharge", 0):,}'),
            ("Stale telemetry", f'{telemetry.get("assets_stale", 0):,} · {source}'),
        ])
    for alert in telemetry.get("alerts") or []:
        st.warning(str(alert.get("message") or "Telemetry requires operator attention."))
    render_summary_grid(st, summary_items)
    asset_labels = {
        str(item.get("asset_id")): str(item.get("asset_name") or item.get("asset_id"))
        for item in assets if item.get("asset_id")
    }
    selected_asset = st.selectbox(
        "Asset detail",
        options=list(asset_labels),
        format_func=lambda value: f"{asset_labels[value]} · {value}",
        help="Select an asset to inspect its latest state and telemetry history.",
    )
    if _asset_presentation_mode(len(assets)) == "cards":
        cards = []
        for item in assets:
            observation = telemetry_assets.get(str(item.get("asset_id") or ""))
            dispatch_count = int(item.get("total_dispatches") or 0)
            average_profit = _numeric(item.get("average_profit_per_dispatch"))
            if average_profit is None and dispatch_count:
                average_profit = (_numeric(item.get("total_profit")) or 0) / dispatch_count
            metrics = [
                ("Power", format_power(item.get("power_mw"))),
                ("Energy", format_energy(item.get("energy_mwh"))),
                ("Dispatches", f"{dispatch_count:,}"),
                ("Revenue", format_currency(item.get("total_revenue"), currency)),
                ("Profit", format_currency(item.get("total_profit"), currency)),
                ("Average profit", "Not available" if average_profit is None else format_currency(average_profit, currency)),
                ("Last dispatch", format_timestamp(item.get("last_dispatch_time"), zone)),
            ]
            soc = None
            status = str(item.get("status") or "Unknown")
            if observation:
                soc_value = _numeric(observation.get("state_of_charge_pct"))
                soc = {"value": max(0, min(100, soc_value)), "label": f"{soc_value:.1f}%"} if soc_value is not None else None
                readiness = observation.get("readiness") or {}
                freshness = observation.get("freshness") or {}
                age_seconds = freshness.get("age_seconds")
                freshness_label = "Not available" if age_seconds is None else f"{age_seconds // 60} min · {freshness.get('status', 'unknown')}"
                metrics.extend([
                    ("Current power", _optional_power(observation.get("current_power_mw"))),
                    ("Charge available", _optional_power(observation.get("available_charge_power_mw"))),
                    ("Discharge available", _optional_power(observation.get("available_discharge_power_mw"))),
                    ("Energy available", _optional_energy(observation.get("available_energy_mwh"))),
                    ("Temperature", "Not available" if observation.get("temperature_c") is None else f'{observation["temperature_c"]:.1f} °C'),
                    ("Operational status", str(observation.get("operational_status") or "Not available").replace("_", " ").title()),
                    ("Readiness", str(readiness.get("explanation") or "Telemetry unavailable")),
                    ("Last telemetry", format_timestamp(observation.get("recorded_at"), zone)),
                    ("Freshness", freshness_label),
                    ("Telemetry source", f'{observation.get("telemetry_source") or "Unknown"} · {"Simulated" if observation.get("is_simulated") else "Operational"}'),
                ])
                status = str(readiness.get("state") or status).replace("_", " ")
            else:
                metrics.extend([
                    ("State of charge", "Telemetry unavailable"),
                    ("Dispatch readiness", "Telemetry unavailable"),
                ])
            cards.append({
                "name": str(item.get("asset_name") or item.get("asset_id") or "Unnamed asset"),
                "technology": str(item.get("technology") or "Technology not recorded"),
                "location": str(item.get("location") or "Location not recorded"),
                "status": status,
                "soc": soc,
                "metrics": metrics,
            })
        render_asset_cards(st, cards)
    else:
        rows = [{
            "Asset": item.get("asset_name") or item.get("asset_id") or "Unnamed asset",
            "Technology": item.get("technology") or "Not recorded",
            "Location": item.get("location") or "Not recorded",
            "Status": item.get("status") or "Unknown",
            "Power MW": _numeric(item.get("power_mw")),
            "Energy MWh": _numeric(item.get("energy_mwh")),
            "SOC %": _numeric(telemetry_assets.get(str(item.get("asset_id") or ""), {}).get("state_of_charge_pct")),
            "Readiness": (telemetry_assets.get(str(item.get("asset_id") or ""), {}).get("readiness") or {}).get("state", "Telemetry unavailable"),
            "Dispatches": int(item.get("total_dispatches") or 0),
            "Revenue": _numeric(item.get("total_revenue")),
            "Profit": _numeric(item.get("total_profit")),
            "Average Profit": _numeric(item.get("average_profit_per_dispatch")),
            "Last Dispatch": format_timestamp(item.get("last_dispatch_time"), zone),
        } for item in assets]
        st.dataframe(rows, width="stretch", hide_index=True)

    history = []
    history_error = None
    if selected_asset and selected_asset in telemetry_assets:
        try:
            history = client.get_telemetry_history(selected_asset)
        except DashboardApiError as exc:
            history_error = str(exc)
            history = [
                item for item in payload.get("telemetry_history") or []
                if str(item.get("asset_id") or "") == selected_asset
            ]
    if history:
        if history_error or payload.get("telemetry_error"):
            st.warning("Telemetry history is temporarily unavailable; latest asset state remains visible.")
        if any(item.get("is_simulated") for item in history):
            st.caption("Telemetry history includes clearly labeled simulated development data.")
        latest = telemetry_assets.get(selected_asset) or {}
        if (latest.get("freshness") or {}).get("stale"):
            st.warning("Telemetry is stale; do not use it as a live dispatch instruction.")
        st.plotly_chart(
            style_chart(
                telemetry_history_figure(
                    history,
                    theme=str(st.session_state.get("pubba_theme_mode") or "dark"),
                ),
                title=f"{selected_asset} telemetry history",
                subtitle="Observed state of charge and current power; gaps are not interpolated.",
                height=390,
                theme=str(st.session_state.get("pubba_theme_mode") or "dark"),
            ),
            width="stretch",
            config=CHART_CONFIG,
        )
    elif selected_asset in telemetry_assets:
        st.caption("Telemetry history is not available; latest asset observations remain visible.")


def _capture_summary(item: dict, currency: str) -> list[tuple[str, str]]:
    economics = item.get("estimated_economics") or {}
    readiness = item.get("operational_readiness") or {}
    return [
        ("Asset", str(item.get("asset_name") or item.get("asset_id") or "Not available")),
        ("Recommendation", str(item.get("recommendation") or "Not available")),
        ("Opportunity score", f'{item.get("opportunity_score", 0)}/100'),
        ("Market price", f'{format_currency(item.get("market_price_per_mwh"), currency)}/MWh'),
        ("Estimated profit", format_currency(economics.get("estimated_gross_profit"), currency) if economics else "Not available"),
        ("Operational readiness", str(readiness.get("explanation") or "Not available")),
    ]


def _opportunities_section(st, payload: dict, currency: str, client, operator=None) -> None:
    render_section_header(st, "Market Opportunities")
    result = payload.get("recommendations")
    if not result:
        message = payload.get("recommendation_error") or "Market opportunity analysis is unavailable."
        st.warning(message)
        st.caption("No operational recommendation is issued while required market inputs are unavailable.")
        return
    recommendations = result.get("recommendations") or []
    best_id = result.get("best_candidate_asset_id")
    best = next((item for item in recommendations if item.get("asset_id") == best_id), None)
    if best:
        economics = best.get("estimated_economics") or {}
        readiness = best.get("operational_readiness") or {}
        render_summary_grid(st, [
            ("Highest score", f'{best.get("opportunity_score", 0)}/100'),
            ("Best candidate", str(best.get("asset_name") or best.get("asset_id"))),
            ("Market condition", str(best.get("recommendation") or "Unavailable")),
            ("Estimated opportunity value", format_currency(economics.get("estimated_gross_profit"), currency) if economics else "Not available"),
            ("Operational readiness", str(readiness.get("explanation") or "Operational readiness awaiting live telemetry.")),
        ])
        if st.button(
            "Prepare Simulation Inputs", key="prepare_recommendation_simulation",
            help="Copies this advisory scenario into the Simulations form without running it.",
        ):
            st.session_state["recommendation_simulation_inputs"] = best.get("simulation_inputs") or {}
            st.success("Simulation inputs prepared. Open Simulations to review and run them manually.")
    st.caption("MARKET OPPORTUNITY is pricing analysis. OPERATIONAL READINESS requires current asset telemetry.")
    for item in recommendations:
        economics = item.get("estimated_economics") or {}
        readiness = item.get("operational_readiness") or {}
        with st.expander(
            f'{item.get("asset_name") or item.get("asset_id")} · '
            f'{item.get("recommendation")} · {item.get("opportunity_score", 0)}/100'
        ):
            st.markdown(f'**MARKET OPPORTUNITY** — {item.get("explanation") or "Unavailable"}')
            st.markdown(f'**OPERATIONAL READINESS** — {readiness.get("explanation") or "Operational readiness awaiting live telemetry."}')
            if economics:
                render_summary_grid(st, [
                    ("Current price", f'{format_currency(economics.get("current_market_price_per_mwh"), currency)}/MWh'),
                    ("Break-even price", f'{format_currency(economics.get("break_even_discharge_price_per_mwh"), currency)}/MWh'),
                    ("Estimated spread", f'{format_currency(economics.get("estimated_spread_per_mwh"), currency)}/MWh'),
                    ("Estimated charging cost", format_currency(economics.get("estimated_charging_cost"), currency)),
                    ("Estimated discharge revenue", format_currency(economics.get("estimated_discharge_revenue"), currency)),
                    ("Estimated gross profit", format_currency(economics.get("estimated_gross_profit"), currency)),
                ])
            for driver in item.get("primary_drivers") or []:
                st.caption(f"• {driver}")
            for risk in item.get("risks") or []:
                st.caption(f"Risk · {risk}")
            st.caption(str(item.get("advisory_notice") or "Advisory analysis only."))
            asset_id = str(item.get("asset_id") or "")
            if not can(operator, "operator", "approver", "admin"):
                st.caption("Operator role or higher is required to capture recommendations.")
            elif not client.recommendation_writes_configured:
                st.caption("Recommendation capture is not enabled for this environment.")
            elif st.button("Capture Recommendation", key=f"capture_recommendation_{asset_id}"):
                st.session_state["pending_recommendation_capture"] = asset_id
            if st.session_state.get("pending_recommendation_capture") == asset_id:
                st.warning("Confirming will store an immutable historical snapshot. It will not dispatch the asset.")
                render_summary_grid(st, _capture_summary(item, currency))
                confirm, cancel = st.columns(2)
                with confirm:
                    if st.button("Confirm Capture", key=f"confirm_capture_{asset_id}", type="primary"):
                        try:
                            response = client.capture_recommendation(asset_id)
                            captured = response.get("recommendation") or {}
                            st.session_state.pop("pending_recommendation_capture", None)
                            if response.get("capture_status") == "duplicate":
                                st.info("An identical recent snapshot already exists. No duplicate record was created.")
                                st.session_state["selected_recommendation_id"] = captured.get("id")
                            else:
                                st.success("Recommendation snapshot captured.")
                        except DashboardApiError as exc:
                            if exc.code == "recommendation_writes_disabled":
                                st.info("Recommendation capture is not enabled for this environment.")
                            else:
                                st.error(f"Recommendation capture failed — {exc}")
                with cancel:
                    if st.button("Cancel", key=f"cancel_capture_{asset_id}"):
                        st.session_state.pop("pending_recommendation_capture", None)


def _render_live(st, client, operator=None) -> None:
    control, action = st.columns([5, 1])
    with control:
        timezone_name = st.text_input("Reporting timezone", placeholder="Use portfolio default", help="Optional IANA timezone such as America/Denver.")
    with action:
        st.write("")
        st.button("Refresh", type="primary", width="stretch", help="Request fresh API, Supabase, and CAISO data now.")
    render_refresh_countdown(
        st,
        theme=THEMES.get(str(st.session_state.get("pubba_theme_mode") or "dark")),
    )
    with st.spinner("Refreshing live operations data…"):
        payload, error = refresh_dashboard_data(st.session_state, client, timezone_name=timezone_name or None)
    if error:
        if payload:
            st.warning(f"Live refresh failed — {error} Previously loaded successful data remains visible.")
        else:
            render_error_state(st, error)
            return
    data = payload.get("dashboard") or {}
    period = data.get("period") or {}
    portfolio = data.get("portfolio") or {}
    zone = period.get("timezone") or portfolio.get("reporting_timezone") or "UTC"
    currency = portfolio.get("currency_code") or "USD"
    kpis = data.get("kpis") or {}
    metadata = data.get("metadata") or {}
    series = data.get("series") or {}
    dispatches = series.get("dispatches") or []
    economic_rows = _dispatch_chart_rows(dispatches, zone)
    assets = payload.get("assets") or []
    refreshed_at = payload.get("refreshed_at")
    total_revenue = sum(row["revenue"] for row in economic_rows)
    total_cost = sum(row["charging_cost"] for row in economic_rows)
    total_profit = sum(row["profit"] for row in economic_rows)
    profit_margin = _margin(total_profit, total_revenue)
    total_discharge = sum(row["discharge_energy_mwh"] for row in economic_rows)
    active_assets = [item for item in assets if str(item.get("status", "")).lower() == "active"]
    total_power = sum(_numeric(item.get("power_mw")) or 0 for item in active_assets)
    total_energy = sum(_numeric(item.get("energy_mwh")) or 0 for item in active_assets)
    current_price = kpis.get("current_market_price_per_mwh")
    financial_classification = str(
        (data.get("data_quality") or {}).get("financial_values") or "not recorded"
    ).replace("_", " ").title()
    render_page_header(
        st,
        "Operations Command Center",
        "Market intelligence, asset operations, and dispatch economics in one platform.",
        badge="Latest data",
        environment="Production",
    )
    reporting_end = period.get("end_at") or metadata.get("generated_at")
    st.caption(
        f"Reporting period · Through {format_timestamp(reporting_end, zone)}"
        f" · Last successful refresh {format_timestamp(refreshed_at, zone)}"
        f" · Data freshness {format_timestamp(metadata.get('data_freshness_at'), zone)}"
    )

    render_section_header(st, "Executive Performance")
    _cards(st, [
        {"label": "Current CAISO RTM Price", "value": "Not available" if current_price is None else f"{format_currency(current_price, currency)}/MWh", "subtitle": f'{metadata.get("market_location") or "Pricing node unavailable"}', "icon": "⌁"},
        {"label": "Active Assets", "value": f"{len(active_assets):,}", "subtitle": "Connected portfolio assets", "icon": "▦"},
        {"label": "Available Power", "value": format_power(total_power), "subtitle": "Configured active-asset capacity", "icon": "⚡"},
        {"label": "Total Energy Capacity", "value": format_energy(total_energy), "subtitle": "Configured active-asset energy", "icon": "▤"},
        {"label": "Portfolio Revenue", "value": format_currency(total_revenue, currency), "subtitle": financial_classification, "icon": "$", "tone": _tone(total_revenue)},
        {"label": "Charging Cost", "value": format_currency(total_cost, currency), "subtitle": "Completed dispatch ledger", "icon": "↓"},
        {"label": "Portfolio Profit", "value": format_currency(total_profit, currency), "subtitle": financial_classification, "icon": "↗", "tone": _tone(total_profit)},
        {"label": "Profit Margin", "value": _percent_label(profit_margin), "subtitle": "Profit divided by revenue", "icon": "%", "tone": _tone(total_profit)},
        {"label": "Completed Dispatches", "value": f"{len(dispatches):,}", "subtitle": f"Reporting timezone · {zone}", "icon": "↔"},
        {"label": "Average Profit / Dispatch", "value": "Not available" if not economic_rows else format_currency(total_profit / len(economic_rows), currency), "subtitle": "Complete economic records", "icon": "◇"},
        {"label": "Total Discharged Energy", "value": format_energy(total_discharge), "subtitle": "Complete dispatch records", "icon": "⇥"},
        {"label": "Last Successful Sync", "value": format_timestamp(kpis.get("last_api_sync_at") or refreshed_at, zone), "subtitle": f"Request latency · {payload.get('latency_ms', 0):.0f} ms", "icon": "◷", "tone": "positive"},
    ])
    _opportunities_section(st, payload, currency, client, operator)
    _market_section(st, data, currency, zone)
    _performance_section(st, data, currency, zone)
    _dispatch_section(st, data, currency, zone)
    _assets_section(st, payload, currency, zone, client)

    render_section_header(st, "Platform Capabilities")
    st.caption("Available today")
    render_capabilities(st, [
        ("CAISO Market Data", "Current and historical CAISO pricing through the existing market-data integration.", "Connected"),
        ("Dispatch Ledger", "Completed dispatch records with energy, revenue, charging cost, and profit.", "FastAPI"),
        ("Portfolio Visibility", "Asset capacity, status, dispatch count, revenue, and profit in one portfolio view.", "Connected"),
        ("Scenario Simulation", "Historical storage economics calculated from selected CAISO market inputs.", "Available"),
        ("System Monitoring", "API, market-data, summary, freshness, and request-latency visibility.", "Available"),
        ("API Architecture", "Dashboard and integrations consume the existing FastAPI service contracts.", "Available"),
    ], status="Available")
    st.caption("Planned capabilities")
    render_capabilities(st, [
        ("Battery Telemetry", "State of charge, operating limits, alarms, and condition data from connected assets.", "Telemetry integration"),
        ("Automated Dispatch", "Coordinated dispatch recommendations and execution workflows across the fleet.", "Optimization engine"),
        ("Price Forecasting", "Forward price and market-condition outlooks for operational planning.", "Forecast service"),
        ("Portfolio Valuation", "Asset value, project returns, and portfolio-level financial analysis.", "Valuation source"),
        ("Alerting", "Configurable operational and market-event notifications.", "Notification service"),
        ("Access Controls", "Multi-user authentication, roles, and permissions.", "Identity service"),
        ("Additional Markets", "Market integrations beyond the current CAISO footprint.", "Market connectors"),
    ])

    render_section_header(st, "System Health")
    checked = format_timestamp(refreshed_at, zone)
    status = data.get("status") or {}
    api_status = str(status.get("api") or "unknown")
    market_status = str(status.get("market_data") or "unknown")
    simulation_status = str(status.get("simulation_engine") or "unknown")
    system_statuses = [
        ("API", api_status.title(), api_status == "connected", f"Checked {checked} · {payload.get('latency_ms', 0):.0f} ms request latency"),
        ("CAISO", market_status.replace("_", " ").title(), market_status == "connected", f"Latest interval {format_timestamp(metadata.get('market_updated_at'), zone)}"),
        ("Dashboard Summary", "Available", True, f"Generated {format_timestamp(metadata.get('generated_at'), zone)}"),
        ("Simulation Engine", simulation_status.title(), simulation_status == "ready", "Historical scenario workflow"),
        ("Reporting Timezone", zone, True, "Applied to dashboard reporting dates"),
        ("Platform Version", "v1.0.0", True, "PUBBA Power operations console"),
    ]
    for source in (data.get("telemetry") or {}).get("source_health") or []:
        source_status = str(source.get("status") or "never_received")
        system_statuses.append((
            f'Telemetry · {source.get("telemetry_source") or "Unknown source"}',
            source_status.replace("_", " ").title(),
            source_status in {"receiving_data", "connected"},
            f'Last received {format_timestamp(source.get("last_received_at"), zone)}',
        ))
    render_system_status(st, system_statuses)
    render_data_freshness(st, format_timestamp(metadata.get("data_freshness_at"), zone))


def render(st, client, operator=None) -> None:
    # Streamlit fragments provide bounded 60-second reruns without re-running navigation.
    st.fragment(run_every=60)(_render_live)(st, client, operator)
