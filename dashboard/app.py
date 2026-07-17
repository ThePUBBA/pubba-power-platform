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


def main() -> None:
    st.set_page_config(
        page_title="PUBBA Power Operations Console",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    install_console_theme(st)
    render_sidebar_brand(st)
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
    render_connection_status(st, "PUBBA Power API configured", connected=True)
    if page == "Overview":
        overview.render(st, client)
    else:
        simulations.render(st, client)
    st.sidebar.divider()
    st.sidebar.caption("© 2026 PUBBA Power  ·  v1.0")


if __name__ == "__main__":
    main()
