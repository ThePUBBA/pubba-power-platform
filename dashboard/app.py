"""Streamlit entry point for the PUBBA Power operations console."""

import streamlit as st

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.auth import configure_operator_identity
from dashboard.components import (
    install_console_theme,
    render_connection_status,
    render_error_state,
    render_sidebar_brand,
)
from dashboard.pages import operators, overview, recommendation_history, simulations
from dashboard.formatting import format_timestamp
from dashboard.refresh import STATE_KEY


def main() -> None:
    st.set_page_config(
        page_title="PUBBA Power Operations Console",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    install_console_theme(st)
    render_sidebar_brand(st)
    st.sidebar.markdown('<span class="pubba-environment">Production</span>', unsafe_allow_html=True)
    try:
        client = Only1ApiClient()
    except DashboardApiError as exc:
        render_connection_status(st, "API configuration required", connected=False)
        render_error_state(st, str(exc))
        return
    operator = configure_operator_identity(st, client)
    pages = ["Overview", "Simulations", "Recommendation History"]
    if operator and operator.get("role") == "admin":
        pages.append("Operator Access")
    page = st.sidebar.radio(
        "Navigation", pages, index=0, label_visibility="collapsed"
    )
    st.sidebar.divider()
    st.sidebar.caption("Portfolio intelligence and storage operations")
    cached = st.session_state.get(STATE_KEY, {}).get("data", {})
    live_status = cached.get("dashboard", {}).get("status", {})
    render_connection_status(
        st, "API connected" if live_status.get("api") == "connected" else "API configured",
        connected=live_status.get("api", "connected") == "connected",
    )
    render_connection_status(
        st,
        "CAISO connected" if live_status.get("market_data") == "connected" else "CAISO awaiting check",
        connected=live_status.get("market_data") == "connected",
    )
    if page == "Overview":
        overview.render(st, client, operator=operator)
    elif page == "Simulations":
        simulations.render(st, client)
    elif page == "Recommendation History":
        recommendation_history.render(st, client, operator=operator)
    else:
        operators.render(st, client, operator=operator)
    st.sidebar.divider()
    refreshed = cached.get("refreshed_at")
    if refreshed:
        st.sidebar.caption(f"Last refresh · {format_timestamp(refreshed, 'UTC')}")
    st.sidebar.caption("© 2026 PUBBA Power  ·  v1.0.0")


if __name__ == "__main__":
    main()
