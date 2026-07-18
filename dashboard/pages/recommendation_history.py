"""Operator-controlled recommendation audit workflow through FastAPI only."""

from __future__ import annotations

from datetime import datetime, time

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import render_page_header, render_section_header, render_summary_grid
from dashboard.formatting import format_currency, format_timestamp


ZONE = "America/Los_Angeles"


def _label(value: object) -> str:
    return str(value or "Not available").replace("_", " ").title()


def _optional_currency(value: object) -> str:
    return "Not available" if value is None else format_currency(value)


def _optional_percent(value: object) -> str:
    return "Not available" if value is None else f"{float(value):.1f}%"


def _link_filter(value: str) -> bool | None:
    return {"Linked": True, "Not linked": False}.get(value)


def _outcome_status(record: dict) -> str:
    if record.get("dispatch_id"):
        return "Dispatch linked"
    if record.get("simulation_id"):
        return "Simulation only"
    return "No action taken"


def _prepare_simulation_inputs(detail: dict) -> dict:
    power = detail.get("power_mw") or detail.get("asset_power_mw")
    energy = detail.get("energy_mwh") or detail.get("asset_energy_mwh")
    duration = detail.get("duration_hours")
    if duration is None and power and energy:
        duration = float(energy) / float(power)
    return {
        "asset_id": detail.get("asset_id"),
        "location": detail.get("market_node"),
        "market": detail.get("market") or "RTM",
        "power_mw": power or 10.0,
        "duration_hours": duration or 4.0,
        "round_trip_efficiency": detail.get("round_trip_efficiency_assumption") or 0.8,
        "storage_fee_per_mwh": detail.get("lease_cost_assumption") or 0,
        "variable_om_per_mwh": detail.get("variable_om_assumption") or 0,
        "market_price_per_mwh": detail.get("market_price"),
        "market_timestamp": detail.get("market_timestamp"),
        "estimated_break_even_price_per_mwh": detail.get("estimated_break_even_price"),
    }


def _filters(st, client: Only1ApiClient) -> dict:
    try:
        assets = client.get_portfolio_assets()
    except DashboardApiError:
        assets = []
    asset_ids = sorted(str(item["asset_id"]) for item in assets if item.get("asset_id"))
    first, second, third = st.columns(3)
    with first:
        asset = st.selectbox("Asset", ["All assets", *asset_ids], key="history_asset")
        direction = st.selectbox(
            "Direction", ["All directions", "charge", "discharge", "hold", "insufficient_data"],
            key="history_direction",
        )
    with second:
        minimum_score = st.number_input(
            "Minimum score", min_value=0, max_value=100, value=0, step=5,
            key="history_minimum_score",
        )
        simulation = st.selectbox(
            "Has simulation", ["Any", "Linked", "Not linked"], key="history_simulation"
        )
    with third:
        dispatch = st.selectbox(
            "Has dispatch", ["Any", "Linked", "Not linked"], key="history_dispatch"
        )
        outcome = st.selectbox(
            "Outcome status",
            ["Any", "No action taken", "Simulation only", "Dispatch linked"],
            key="history_outcome",
        )
    use_dates = st.checkbox("Filter by generated date", key="history_use_dates")
    outcome_status = {
        "No action taken": "no_action_taken",
        "Simulation only": "simulation_only",
        "Dispatch linked": "dispatch_linked",
    }.get(outcome)
    filters: dict = {
        "asset_id": None if asset == "All assets" else asset,
        "direction": None if direction == "All directions" else direction,
        "minimum_score": int(minimum_score),
        "linked_simulation": None if outcome_status else _link_filter(simulation),
        "linked_dispatch": None if outcome_status else _link_filter(dispatch),
        "outcome_status": outcome_status,
        "limit": 250,
    }
    if use_dates:
        start, end = st.date_input("Generated date range", value=(datetime.now().date(), datetime.now().date()))
        filters["start_time"] = datetime.combine(start, time.min).astimezone().isoformat()
        filters["end_time"] = datetime.combine(end, time.max).astimezone().isoformat()
    return filters


def _render_analytics(st, analytics: dict) -> None:
    render_section_header(st, "Portfolio Audit Summary")
    render_summary_grid(st, [
        ("Captured recommendations", f'{analytics.get("recommendations_captured", 0):,}'),
        ("Acknowledged", f'{analytics.get("recommendations_acknowledged", 0):,}'),
        ("Simulated", f'{analytics.get("recommendations_simulated", 0):,}'),
        ("Dispatch linked", f'{analytics.get("recommendations_linked_to_dispatch", 0):,}'),
        ("Completed linked outcomes", f'{analytics.get("completed_linked_outcomes", analytics.get("linked_outcome_sample_size", 0)):,}'),
        ("Estimated opportunity value", _optional_currency(analytics.get("estimated_opportunity_value"))),
        ("Realized linked profit", _optional_currency(analytics.get("realized_profit"))),
        ("Estimated vs realized variance", _optional_currency(analytics.get("estimated_vs_realized_profit_variance"))),
    ])
    st.caption(f'Linked outcome sample size · {analytics.get("linked_outcome_sample_size", 0):,}')
    st.caption(str(analytics.get("accuracy_message") or "Model accuracy is not available."))


def _safe_rerun(st) -> None:
    if hasattr(st, "rerun"):
        st.rerun()


def _operator_actions(st, client: Only1ApiClient, detail: dict) -> None:
    render_section_header(st, "Operator Actions")
    if not client.recommendation_writes_configured:
        st.info("Recommendation capture is not enabled for this environment.")
    recommendation_id = str(detail["id"])
    acknowledge, prepare = st.columns(2)
    with acknowledge:
        if detail.get("acknowledged_at"):
            st.success(
                f'Acknowledged {format_timestamp(detail.get("acknowledged_at"), ZONE)} · '
                f'{detail.get("acknowledgement_attribution") or "system"}'
            )
        else:
            note = st.text_input("Acknowledgement note (optional)", key=f"ack_note_{recommendation_id}")
            confirmed = st.checkbox(
                "Confirm acknowledgement", key=f"ack_confirm_{recommendation_id}"
            )
            if st.button("Acknowledge Recommendation", key=f"ack_{recommendation_id}", disabled=not confirmed):
                try:
                    client.acknowledge_recommendation(recommendation_id, note)
                    st.success("Recommendation acknowledged and persisted.")
                    _safe_rerun(st)
                except DashboardApiError as exc:
                    st.error(f"Acknowledgement failed — {exc}")
    with prepare:
        st.caption("Copy persisted assumptions into the simulation form for operator review.")
        if st.button("Prepare Simulation", key=f"prepare_{recommendation_id}"):
            st.session_state["recommendation_simulation_inputs"] = _prepare_simulation_inputs(detail)
            st.success("Simulation inputs prepared. Open Simulations to review them; nothing was run.")

    simulation, dispatch = st.columns(2)
    with simulation:
        st.caption("LINK EXISTING SIMULATION")
        if detail.get("simulation_id"):
            st.info(f'Simulation linked · {detail["simulation_id"]}')
        else:
            try:
                candidates = client.get_simulations(asset_id=str(detail["asset_id"]), limit=100)
            except DashboardApiError as exc:
                candidates = []
                st.warning(f"Simulations are unavailable — {exc}")
            if not candidates:
                st.caption("No simulations are available for this portfolio and asset.")
            else:
                ids = [str(item["id"]) for item in candidates if item.get("id")]
                selected = st.selectbox(
                    "Simulation", ids, key=f"simulation_{recommendation_id}",
                    format_func=lambda value: next(
                        f'{format_timestamp(item.get("created_at"), ZONE)} · '
                        f'{_optional_currency(item.get("estimated_net_margin"))} · {value}'
                        for item in candidates if str(item.get("id")) == value
                    ),
                )
                confirmed = st.checkbox("Confirm simulation link", key=f"simulation_confirm_{recommendation_id}")
                if st.button("Link Existing Simulation", key=f"link_simulation_{recommendation_id}", disabled=not confirmed):
                    try:
                        client.link_recommendation_simulation(recommendation_id, selected)
                        st.success("Simulation linked by stable database ID.")
                        _safe_rerun(st)
                    except DashboardApiError as exc:
                        st.error(f"Simulation link failed — {exc}")
    with dispatch:
        st.caption("LINK EXISTING DISPATCH")
        if detail.get("dispatch_id"):
            st.info(f'Dispatch linked · {detail["dispatch_id"]}')
        else:
            try:
                candidates = client.get_dispatch_events(asset_id=str(detail["asset_id"]), limit=100)
            except DashboardApiError as exc:
                candidates = []
                st.warning(f"Dispatches are unavailable — {exc}")
            if not candidates:
                st.caption("No dispatches are available for this portfolio and asset.")
            else:
                ids = [str(item["id"]) for item in candidates if item.get("id")]
                selected = st.selectbox(
                    "Dispatch", ids, key=f"dispatch_{recommendation_id}",
                    format_func=lambda value: next(
                        f'{format_timestamp(item.get("dispatch_timestamp"), ZONE)} · '
                        f'{_label(item.get("status"))} · {value}'
                        for item in candidates if str(item.get("id")) == value
                    ),
                )
                confirmed = st.checkbox("Confirm dispatch link", key=f"dispatch_confirm_{recommendation_id}")
                if st.button("Link Existing Dispatch", key=f"link_dispatch_{recommendation_id}", disabled=not confirmed):
                    try:
                        client.link_recommendation_dispatch(recommendation_id, selected)
                        st.success("Dispatch linked by stable database ID; no causation was inferred.")
                        _safe_rerun(st)
                    except DashboardApiError as exc:
                        st.error(f"Dispatch link failed — {exc}")


def _render_outcome(st, detail: dict) -> None:
    render_section_header(st, "Outcome")
    outcome = detail.get("outcome") or {}
    estimated = outcome.get("estimated") or {}
    realized = outcome.get("realized") or {}
    variance = outcome.get("variance") or {}
    render_summary_grid(st, [
        ("Outcome status", _label(outcome.get("status"))),
        ("Estimated revenue", _optional_currency(estimated.get("revenue"))),
        ("Estimated charging cost", _optional_currency(estimated.get("charging_cost"))),
        ("Estimated profit", _optional_currency(estimated.get("profit"))),
        ("Estimated margin", _optional_percent(estimated.get("margin_pct"))),
        ("Realized revenue", _optional_currency(realized.get("revenue"))),
        ("Realized charging cost", _optional_currency(realized.get("charging_cost"))),
        ("Realized profit", _optional_currency(realized.get("profit"))),
        ("Realized margin", _optional_percent(realized.get("margin_pct"))),
        ("Revenue variance", _optional_currency((variance.get("revenue") or {}).get("absolute"))),
        ("Charging-cost variance", _optional_currency((variance.get("charging_cost") or {}).get("absolute"))),
        ("Profit variance", _optional_currency((variance.get("profit") or {}).get("absolute"))),
        ("Margin variance", _optional_percent((variance.get("margin_pct") or {}).get("absolute"))),
    ])


def render(st, client: Only1ApiClient) -> None:
    render_page_header(
        st, "Recommendation History",
        "Immutable advisory snapshots, explicit operator decisions, and linked outcomes.",
        badge="Decision audit", environment="Production",
    )
    st.caption("Historical snapshots are advisory records and do not imply dispatch causation.")
    render_section_header(st, "History Filters")
    filters = _filters(st, client)
    try:
        records = client.get_recommendation_history(**filters)
        analytics = client.get_recommendation_history_analytics()
    except DashboardApiError as exc:
        st.warning(f"Recommendation history is unavailable — {exc}")
        return
    _render_analytics(st, analytics)
    if not records:
        st.info("No recommendations have been explicitly captured for these filters.")
        return

    st.dataframe([{
        "Generated": format_timestamp(item.get("generated_at"), ZONE),
        "Asset": item.get("asset_id"), "Recommendation": item.get("recommendation"),
        "Direction": _label(item.get("recommendation_direction")),
        "Score": item.get("opportunity_score"),
        "Market Price": _optional_currency(item.get("market_price")),
        "Estimated Profit": _optional_currency(item.get("estimated_gross_profit")),
        "Readiness": _label(item.get("operational_readiness")),
        "Outcome": _outcome_status(item),
    } for item in records], width="stretch", hide_index=True)
    ids = [str(item["id"]) for item in records]
    preferred = st.session_state.pop("selected_recommendation_id", None)
    selected_id = st.selectbox(
        "Historical recommendation", ids,
        index=ids.index(preferred) if preferred in ids else 0,
        format_func=lambda value: next(
            f'{item.get("asset_id")} · {item.get("recommendation")} · {item.get("opportunity_score")}/100'
            for item in records if str(item["id"]) == value
        ),
    )
    try:
        detail = client.get_recommendation_history_detail(selected_id)
    except DashboardApiError as exc:
        st.warning(f"Historical detail is unavailable — {exc}")
        return

    render_section_header(st, "Original Recommendation")
    render_summary_grid(st, [
        ("Generated", format_timestamp(detail.get("generated_at"), ZONE)),
        ("Captured", format_timestamp(detail.get("captured_at"), ZONE)),
        ("Asset", str(detail.get("asset_id") or "Not available")),
        ("Market price", f'{_optional_currency(detail.get("market_price"))}/MWh'),
        ("Score", f'{detail.get("opportunity_score", 0)}/100'),
        ("Recommendation", detail.get("recommendation") or "Not available"),
        ("Estimated profit", _optional_currency(detail.get("estimated_gross_profit"))),
        ("Operational readiness", _label(detail.get("operational_readiness"))),
    ])
    st.markdown(str(detail.get("explanation") or "Explanation unavailable."))
    _operator_actions(st, client, detail)

    comparison = detail.get("simulation_comparison")
    if comparison:
        render_section_header(st, "Simulation Comparison")
        render_summary_grid(st, [
            ("Simulation ID", str(detail.get("simulation_id"))),
            ("Original recommendation estimate", _optional_currency(comparison.get("recommendation_estimated_profit"))),
            ("Simulation estimate", _optional_currency(comparison.get("simulation_estimated_profit"))),
            ("Difference", _optional_currency(comparison.get("profit_difference"))),
        ])
    dispatch = detail.get("dispatch") or {}
    if dispatch:
        render_section_header(st, "Linked Dispatch")
        render_summary_grid(st, [
            ("Dispatch ID", str(detail.get("dispatch_id"))),
            ("Status", _label(dispatch.get("status"))),
            ("Estimated economics", _optional_currency(detail.get("estimated_gross_profit"))),
            ("Realized economics", _optional_currency(dispatch.get("net_profit")) if str(dispatch.get("status", "")).lower() == "completed" else "Not available"),
            ("Variance", _optional_currency((((detail.get("outcome") or {}).get("variance") or {}).get("profit") or {}).get("absolute"))),
        ])

    render_section_header(st, "Decision Timeline")
    timeline = detail.get("decision_timeline") or []
    if timeline:
        st.dataframe([{
            "Time": format_timestamp(item.get("timestamp"), ZONE),
            "Persisted event": _label(item.get("event")),
            "Attribution": item.get("attribution") or "system",
        } for item in timeline], width="stretch", hide_index=True)
    else:
        st.caption("No persisted decision events are available.")
    _render_outcome(st, detail)
