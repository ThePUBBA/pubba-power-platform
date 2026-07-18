"""Shared enterprise Plotly styling and chart builders."""

from __future__ import annotations

import plotly.graph_objects as go


MINT = "#44FFBB"
WHITE = "#FFFFFF"
MUTED = "#A7A7A7"
GRID = "#2F2F2F"
GRAY = "#737373"
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def observation_mode(count: int) -> str:
    """Describe the honest visual treatment for the available observation count."""
    if count <= 1:
        return "single"
    if count <= 3:
        return "sparse"
    return "categorical"


def style_chart(
    fig: go.Figure,
    *,
    title: str,
    subtitle: str = "",
    y_title: str = "",
    height: int = 370,
) -> go.Figure:
    title_text = title + (
        f"<br><sup style='color:{MUTED};font-family:Inter,Arial,sans-serif'>"
        f"{subtitle}</sup>" if subtitle else ""
    )
    fig.update_layout(
        title={
            "text": title_text,
            "font": {
                "size": 18,
                "color": WHITE,
                "family": "Bebas Neue, Arial Narrow, Arial, sans-serif",
            },
        },
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": WHITE, "family": "Inter, Arial, sans-serif", "size": 12},
        margin={"l": 64, "r": 52, "t": 82, "b": 68},
        hovermode="closest",
        hoverlabel={"bgcolor": "#1C1C1C", "bordercolor": GRID, "font_color": WHITE},
        legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(
        gridcolor=GRID,
        zeroline=False,
        tickfont={"color": MUTED},
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=GRID,
        zeroline=False,
        title=y_title,
        tickfont={"color": MUTED},
        automargin=True,
        exponentformat="none",
        showexponent="none",
    )
    return fig


def daily_financial_figure(rows: list[dict]) -> go.Figure:
    """Compare actual daily revenue, charging cost, and retained profit."""
    dates = [row["label"] for row in rows]
    custom = [
        [row["revenue"], row["charging_cost"], row["profit"], row["profit_margin_label"]]
        for row in rows
    ]
    fig = go.Figure()
    for field, name, color in (
        ("revenue", "Gross revenue", MINT),
        ("charging_cost", "Charging cost", GRAY),
        ("profit", "Net profit", WHITE),
    ):
        fig.add_bar(
            x=dates,
            y=[row[field] for row in rows],
            name=name,
            marker={"color": color},
            customdata=custom,
            hovertemplate=(
                "%{x}<br>Gross revenue $%{customdata[0]:,.2f}"
                "<br>Charging cost $%{customdata[1]:,.2f}"
                "<br>Net profit $%{customdata[2]:,.2f}"
                "<br>Profit margin %{customdata[3]}<extra></extra>"
            ),
        )
    fig.update_layout(
        barmode="group",
        bargap=0.34 if observation_mode(len(rows)) == "single" else 0.24,
        bargroupgap=0.08,
        showlegend=True,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=dates)
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", separatethousands=True)
    return fig


def daily_energy_figure(rows: list[dict]) -> go.Figure:
    """Compare charged and discharged energy using returned dispatch values."""
    dates = [row["label"] for row in rows]
    custom = [
        [
            row["charge_energy_mwh"],
            row["discharge_energy_mwh"],
            row["efficiency_label"],
        ]
        for row in rows
    ]
    fig = go.Figure()
    for field, name, color in (
        ("charge_energy_mwh", "Charge energy", GRAY),
        ("discharge_energy_mwh", "Discharge energy", MINT),
    ):
        fig.add_bar(
            x=dates,
            y=[row[field] for row in rows],
            name=name,
            marker={"color": color},
            customdata=custom,
            hovertemplate=(
                "%{x}<br>Charge energy %{customdata[0]:,.2f} MWh"
                "<br>Discharge energy %{customdata[1]:,.2f} MWh"
                "<br>Energy ratio %{customdata[2]}<extra></extra>"
            ),
        )
    fig.update_layout(
        barmode="group",
        bargap=0.38 if observation_mode(len(rows)) == "single" else 0.28,
        bargroupgap=0.1,
        showlegend=True,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=dates)
    fig.update_yaxes(tickformat=",.0f", separatethousands=True)
    return fig


def dispatch_economics_figure(rows: list[dict]) -> go.Figure:
    """Compare revenue, charging cost, and profit for each returned dispatch."""
    labels = [row["label"] for row in rows]
    custom = [
        [
            row["timestamp_label"],
            row["asset"],
            row["charge_energy_mwh"],
            row["discharge_energy_mwh"],
            row["revenue"],
            row["charging_cost"],
            row["profit"],
            row["profit_margin_label"],
            row["market"],
            row["node"],
            row["classification"],
        ]
        for row in rows
    ]
    patterns = ["/" if row["classification_key"] != "operational" else "" for row in rows]
    fig = go.Figure()
    for field, name, color in (
        ("revenue", "Revenue", MINT),
        ("charging_cost", "Charging cost", GRAY),
        ("profit", "Profit", WHITE),
    ):
        fig.add_bar(
            x=labels,
            y=[row[field] for row in rows],
            name=name,
            marker={"color": color, "pattern": {"shape": patterns}},
            customdata=custom,
            hovertemplate=(
                "%{customdata[0]}<br>Asset %{customdata[1]}"
                "<br>Charge %{customdata[2]:,.2f} MWh"
                "<br>Discharge %{customdata[3]:,.2f} MWh"
                "<br>Revenue $%{customdata[4]:,.2f}"
                "<br>Charging cost $%{customdata[5]:,.2f}"
                "<br>Profit $%{customdata[6]:,.2f}"
                "<br>Profit margin %{customdata[7]}"
                "<br>Market %{customdata[8]} · Node %{customdata[9]}"
                "<br>Classification %{customdata[10]}<extra></extra>"
            ),
        )
    fig.update_layout(
        barmode="group",
        bargap=0.3 if observation_mode(len(rows)) == "single" else 0.2,
        bargroupgap=0.08,
        showlegend=True,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=labels)
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", separatethousands=True)
    return fig


def trend_figure(rows: list[dict], field: str, *, name: str, color: str, currency: bool) -> go.Figure:
    categorical = len(rows) == 1
    trace = go.Scatter(
        x=[row["date"] for row in rows],
        y=[row[field] for row in rows],
        name=name,
        mode="markers" if categorical else "lines+markers",
        line={"color": color, "width": 3},
        marker={"color": color, "size": 10},
        hovertemplate=("%{x}<br>$%{y:,.2f}<extra></extra>" if currency else "%{x}<br>%{y:,.2f}<extra></extra>"),
    )
    fig = go.Figure(trace)
    if currency:
        fig.update_yaxes(tickprefix="$", tickformat=",.2f", separatethousands=True)
    if categorical:
        fig.update_xaxes(type="category")
    return fig


def telemetry_history_figure(rows: list[dict]) -> go.Figure:
    """Plot observed SOC and current power without interpolating large gaps."""
    ordered = sorted(rows, key=lambda row: str(row.get("recorded_at") or ""))
    fig = go.Figure()
    soc_rows = [row for row in ordered if row.get("state_of_charge_pct") is not None]
    power_rows = [row for row in ordered if row.get("current_power_mw") is not None]
    if soc_rows:
        fig.add_scatter(
            x=[row["recorded_at"] for row in soc_rows],
            y=[row["state_of_charge_pct"] for row in soc_rows],
            name="State of charge", yaxis="y", connectgaps=False,
            mode="markers" if len(soc_rows) == 1 else "lines+markers",
            line={"color": MINT, "width": 3}, marker={"color": MINT, "size": 8},
            customdata=[["Simulated" if row.get("is_simulated") else "Operational"] for row in soc_rows],
            hovertemplate="%{x|%b %d, %Y · %I:%M %p}<br>%{y:.1f}% SOC<br>%{customdata[0]}<extra></extra>",
        )
    if power_rows:
        fig.add_scatter(
            x=[row["recorded_at"] for row in power_rows],
            y=[row["current_power_mw"] for row in power_rows],
            name="Current power", yaxis="y2", connectgaps=False,
            mode="markers" if len(power_rows) == 1 else "lines+markers",
            line={"color": WHITE, "width": 2}, marker={"color": WHITE, "size": 7},
            customdata=[["Simulated" if row.get("is_simulated") else "Operational"] for row in power_rows],
            hovertemplate="%{x|%b %d, %Y · %I:%M %p}<br>%{y:.2f} MW<br>%{customdata[0]}<extra></extra>",
        )
    fig.update_layout(
        yaxis={"title": "SOC (%)", "range": [0, 100]},
        yaxis2={"title": "Power (MW)", "overlaying": "y", "side": "right", "showgrid": False},
        showlegend=True,
    )
    fig.update_xaxes(type="date", tickformat="%I:%M %p\n%b %d", nticks=8)
    return fig
