"""Existing storage simulation workflow presented through FastAPI."""

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import (
    render_kpi_card,
    render_page_header,
    render_section_header,
)
from dashboard.formatting import as_decimal, format_currency, format_energy


def render(st, client: Only1ApiClient) -> None:
    render_page_header(
        st,
        "Storage Simulations",
        "Evaluate historical CAISO storage economics using the existing portfolio workflow.",
        badge="Historical analysis",
    )
    render_section_header(st, "Simulation parameters")
    with st.form("simulation"):
        left, right = st.columns(2)
        with left:
            location = st.text_input("CAISO pricing node", "TH_NP15_GEN-APND")
            market = st.selectbox("Market", ["RTM", "DAM", "HASP", "RTPD"])
            simulation_date = st.date_input("Trade date")
            power_mw = st.number_input("Power capacity (MW)", min_value=0.01, value=10.0)
            duration_hours = st.number_input("Duration (hours)", min_value=0.01, value=4.0)
        with right:
            efficiency = st.number_input(
                "Round-trip efficiency", min_value=0.01, max_value=1.0, value=0.8
            )
            cycles = st.number_input("Cycles", min_value=0.01, value=1.0)
            storage_fee = st.number_input("Storage fee (USD/MWh)", min_value=0.0)
            variable_om = st.number_input("Variable O&M (USD/MWh)", min_value=0.0)
            asset_id = st.text_input("Asset ID (optional)")
        submitted = st.form_submit_button("Run simulation", type="primary")

    if not submitted:
        return
    request = {
        "location": location,
        "market": market,
        "date": simulation_date.isoformat(),
        "power_mw": power_mw,
        "duration_hours": duration_hours,
        "round_trip_efficiency": efficiency,
        "cycles": cycles,
        "storage_fee_per_mwh": storage_fee,
        "variable_om_per_mwh": variable_om,
    }
    if asset_id.strip():
        request["asset_id"] = asset_id.strip()
    try:
        with st.spinner("Running historical simulation…"):
            result = client.run_simulation(request)
    except DashboardApiError as exc:
        st.error(f"Simulation unavailable — {exc}")
        return

    render_section_header(st, "Simulation results")
    net, revenue, energy = st.columns(3)
    with net:
        render_kpi_card(
            st,
            "Estimated Net Margin",
            format_currency(result["estimated_net_margin"]),
            tone=(
                "positive"
                if as_decimal(result["estimated_net_margin"]) > 0
                else "negative"
            ),
        )
    with revenue:
        render_kpi_card(
            st, "Discharge Revenue", format_currency(result["discharge_revenue"])
        )
    with energy:
        render_kpi_card(
            st, "Discharged Energy", format_energy(result["discharged_energy_mwh"])
        )
    persistence = result.get("persistence") or {}
    if persistence:
        st.caption(f"Persistence: {persistence.get('message', 'Status unavailable')}")
