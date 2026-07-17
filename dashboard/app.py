"""Streamlit entry point for the PUBBA Power operations console."""

import streamlit as st

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import (
    install_console_theme,
    render_connection_status,
    render_error_state,
    render_sidebar_brand,
)
from dashboard.pages import overview, simulations
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
    page = st.sidebar.radio(
        "Navigation", ["Overview", "Simulations"], index=0, label_visibility="collapsed"
    )
    st.sidebar.divider()
    st.sidebar.caption("Portfolio intelligence and storage operations")
    try:
        client = Only1ApiClient()
    except DashboardApiError as exc:
        render_connection_status(st, "API configuration required", connected=False)
        render_error_state(st, str(exc))
        return
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
        overview.render(st, client)
    else:
        simulations.render(st, client)
    st.sidebar.divider()
    refreshed = cached.get("refreshed_at")
    if refreshed:
        st.sidebar.caption(f"Last refresh · {format_timestamp(refreshed, 'UTC')}")
    st.sidebar.caption("© 2026 PUBBA Power  ·  v1.0.0")


if __name__ == "__main__":
    main()
