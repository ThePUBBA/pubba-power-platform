"""Shared enterprise Plotly styling and chart builders."""

from __future__ import annotations

import plotly.graph_objects as go


MINT = "#44FFBB"
WHITE = "#FFFFFF"
MUTED = "#A7A7A7"
GRID = "#2F2F2F"
GRAY = "#737373"


def style_chart(
    fig: go.Figure,
    *,
    title: str,
    subtitle: str = "",
    y_title: str = "",
    height: int = 370,
) -> go.Figure:
    title_text = title + (f"<br><sup style='color:{MUTED}'>{subtitle}</sup>" if subtitle else "")
    fig.update_layout(
        title={"text": title_text, "font": {"size": 18, "color": WHITE}},
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": WHITE, "family": "Inter, Arial, sans-serif", "size": 12},
        margin={"l": 55, "r": 24, "t": 78, "b": 45},
        hovermode="closest",
        hoverlabel={"bgcolor": "#1C1C1C", "bordercolor": GRID, "font_color": WHITE},
        legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, tickfont={"color": MUTED})
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=y_title, tickfont={"color": MUTED})
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
