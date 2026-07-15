"""Streamlit entry point for the Only1 Power operations dashboard."""

import streamlit as st

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import install_console_theme, render_error_state
from dashboard.pages import overview, simulations


def main() -> None:
    st.set_page_config(
        page_title="Only1 Power Operations",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    install_console_theme(st)
    st.sidebar.markdown("## Only1 Power")
    st.sidebar.caption("Operations Intelligence")
    page = st.sidebar.radio("Navigation", ["Overview", "Simulations"], index=0)
    st.sidebar.divider()
    st.sidebar.caption("Metrics are supplied by the Only1 FastAPI service.")
    try:
        client = Only1ApiClient()
    except DashboardApiError as exc:
        render_error_state(st, str(exc))
        return
    if page == "Overview":
        overview.render(st, client)
    else:
        simulations.render(st, client)


if __name__ == "__main__":
    main()

