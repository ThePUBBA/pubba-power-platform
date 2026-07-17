"""Enterprise historical storage simulation workflow presented through FastAPI."""

import plotly.graph_objects as go

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.charts import CHART_CONFIG, GRAY, MINT, style_chart
from dashboard.components import (
    render_kpi_card,
    render_notice,
    render_page_header,
    render_section_header,
)
from dashboard.formatting import as_decimal, format_currency, format_energy, format_timestamp


def render(st, client: Only1ApiClient) -> None:
    render_page_header(
        st, "Storage Simulations",
        "Evaluate calculated storage economics against historical CAISO market prices.",
        badge="Calculated analysis", environment="Production",
    )
    render_notice(
        st,
        "Simulation outputs are calculated estimates based on historical market "
        "data—not executed operational dispatches.",
    )
    render_section_header(st, "Simulation Parameters")
    with st.form("simulation"):
        market_col, asset_col = st.columns(2)
        with market_col:
            st.caption("MARKET INPUTS")
            location = st.text_input("CAISO pricing node", "TH_NP15_GEN-APND", help="The CAISO pricing node used for historical LMP data.")
            market = st.selectbox("Market type", ["RTM", "DAM", "HASP", "RTPD"], help="CAISO market run used for the price series.")
            simulation_date = st.date_input("Historical trade date", help="The historical date evaluated by the simulation.")
        with asset_col:
            st.caption("STORAGE ASSUMPTIONS")
            power_mw = st.number_input("Power capacity (MW)", min_value=0.01, value=10.0, help="Maximum charge or discharge power.")
            duration_hours = st.number_input("Duration (hours)", min_value=0.01, value=4.0)
            efficiency = st.number_input("Round-trip efficiency", min_value=0.01, max_value=1.0, value=0.8, format="%.2f")
            cycles = st.number_input("Cycles", min_value=0.01, value=1.0)
        cost_a, cost_b, identity = st.columns(3)
        with cost_a:
            storage_fee = st.number_input("Storage fee (USD/MWh)", min_value=0.0)
        with cost_b:
            variable_om = st.number_input("Variable O&M (USD/MWh)", min_value=0.0)
        with identity:
            asset_id = st.text_input("Asset ID (optional)", help="Associates the calculated result with an existing asset when supplied.")
        submitted = st.form_submit_button("Run Historical Simulation", type="primary", width="stretch")

    if not submitted:
        st.caption("Configure the historical market and storage assumptions, then run the simulation.")
        return
    request = {
        "location": location, "market": market, "date": simulation_date.isoformat(),
        "power_mw": power_mw, "duration_hours": duration_hours,
        "round_trip_efficiency": efficiency, "cycles": cycles,
        "storage_fee_per_mwh": storage_fee, "variable_om_per_mwh": variable_om,
    }
    if asset_id.strip():
        request["asset_id"] = asset_id.strip()
    try:
        with st.spinner("Loading historical CAISO prices and calculating storage economics…"):
            result = client.run_simulation(request)
    except DashboardApiError as exc:
        st.error(f"Simulation unavailable — {exc}")
        st.caption("No calculated result was persisted from this failed request.")
        return

    render_section_header(st, "Calculated Results")
    cards = st.columns(4)
    values = [
        ("Estimated Net Profit", result.get("estimated_net_margin"), "Calculated after modeled costs", "positive" if as_decimal(result.get("estimated_net_margin")) > 0 else "negative"),
        ("Estimated Revenue", result.get("discharge_revenue"), "Calculated discharge revenue", "neutral"),
        ("Estimated Charging Cost", result.get("charging_cost"), "Historical-price input", "neutral"),
        ("Discharged Energy", None, "Calculated energy output", "neutral"),
    ]
    for column, (label, value, subtitle, tone) in zip(cards, values):
        with column:
            display = format_energy(result.get("discharged_energy_mwh")) if label == "Discharged Energy" else format_currency(value)
            render_kpi_card(st, label, display, subtitle=subtitle, tone=tone)

    charge = result.get("charging_window") or {}
    discharge = result.get("discharging_window") or {}
    charge_points = charge.get("prices") or []
    discharge_points = discharge.get("prices") or []
    if charge_points or discharge_points:
        render_section_header(st, "Historical Market Windows")
        fig = go.Figure()
        if charge_points:
            charge_times = [format_timestamp(p["timestamp"], "America/Los_Angeles") for p in charge_points]
            fig.add_trace(go.Scatter(x=charge_times, y=[p["price"] for p in charge_points], customdata=charge_times, name="Charge window", line={"color": GRAY, "width": 3}, hovertemplate="%{customdata}<br>$%{y:,.2f}/MWh<extra></extra>"))
        if discharge_points:
            discharge_times = [format_timestamp(p["timestamp"], "America/Los_Angeles") for p in discharge_points]
            fig.add_trace(go.Scatter(x=discharge_times, y=[p["price"] for p in discharge_points], customdata=discharge_times, name="Discharge window", line={"color": MINT, "width": 3}, hovertemplate="%{customdata}<br>$%{y:,.2f}/MWh<extra></extra>"))
        fig.update_xaxes(type="category")
        st.plotly_chart(
            style_chart(
                fig,
                title="Historical charge and discharge windows",
                subtitle=f"{market} · {location} · {simulation_date.isoformat()}",
                y_title="USD/MWh",
            ),
            width="stretch",
            config=CHART_CONFIG,
        )

    with st.expander("Simulation assumptions and classification"):
        st.json({
            "classification": "Calculated estimate using historical market data",
            "market": market, "pricing_node": location, "trade_date": simulation_date.isoformat(),
            "power_mw": power_mw, "duration_hours": duration_hours,
            "round_trip_efficiency": efficiency, "cycles": cycles,
            "storage_fee_per_mwh": storage_fee, "variable_om_per_mwh": variable_om,
        })
    persistence = result.get("persistence") or {}
    if persistence:
        st.caption(f"Ledger persistence: {persistence.get('message', 'Status unavailable')} · Classification: simulated/calculated")
