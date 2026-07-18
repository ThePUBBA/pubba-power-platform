"""Historical recommendation snapshots and explicitly linked outcomes."""

from __future__ import annotations

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import render_page_header, render_section_header, render_summary_grid
from dashboard.formatting import format_currency, format_timestamp


def _label(value: object) -> str:
    return str(value or "Not available").replace("_", " ").title()


def render(st, client: Only1ApiClient) -> None:
    render_page_header(
        st, "Recommendation History",
        "Immutable advisory snapshots, explicit decision links, and realized outcomes.",
        badge="Decision audit", environment="Production",
    )
    st.caption("Historical snapshots are not live recommendations and do not imply dispatch causation.")
    try:
        records = client.get_recommendation_history(limit=250)
        analytics = client.get_recommendation_history_analytics()
    except DashboardApiError as exc:
        st.warning(f"Recommendation history is unavailable — {exc}")
        st.caption("The live Operations Command Center remains available. Apply the reviewed history migration before enabling audit writes.")
        return

    render_section_header(st, "Portfolio Audit Summary")
    render_summary_grid(st, [
        ("Captured", f'{analytics.get("recommendations_captured", 0):,}'),
        ("Acknowledged", f'{analytics.get("recommendations_acknowledged", 0):,}'),
        ("Simulated", f'{analytics.get("recommendations_simulated", 0):,}'),
        ("Linked dispatches", f'{analytics.get("recommendations_linked_to_dispatch", 0):,}'),
        ("Average score", "Not available" if analytics.get("average_opportunity_score") is None else f'{analytics["average_opportunity_score"]:.1f}/100'),
        ("Linked outcome sample", f'{analytics.get("linked_outcome_sample_size", 0):,}'),
    ])
    st.caption(str(analytics.get("accuracy_message") or "Model accuracy is not available."))
    if not records:
        st.info("No recommendations have been explicitly captured.")
        return

    asset_options = sorted({str(item.get("asset_id")) for item in records if item.get("asset_id")})
    asset_filter = st.selectbox("Asset filter", ["All assets", *asset_options])
    filtered = records if asset_filter == "All assets" else [
        item for item in records if item.get("asset_id") == asset_filter
    ]
    st.dataframe([{
        "Generated": format_timestamp(item.get("generated_at"), "America/Los_Angeles"),
        "Asset": item.get("asset_id"),
        "Recommendation": item.get("recommendation"),
        "Score": item.get("opportunity_score"),
        "Market Price": format_currency(item.get("market_price")),
        "Estimated Profit": format_currency(item.get("estimated_gross_profit")),
        "Readiness": _label(item.get("operational_readiness")),
        "Outcome": "Dispatch linked" if item.get("dispatch_id") else "Simulation only" if item.get("simulation_id") else "No action taken",
    } for item in filtered], width="stretch", hide_index=True)

    selected_id = st.selectbox(
        "Historical recommendation",
        [str(item["id"]) for item in filtered],
        format_func=lambda value: next(
            f'{item.get("asset_id")} · {item.get("recommendation")} · {item.get("opportunity_score")}/100'
            for item in filtered if str(item["id"]) == value
        ),
    )
    try:
        detail = client.get_recommendation_history_detail(selected_id)
    except DashboardApiError as exc:
        st.warning(f"Historical detail is unavailable — {exc}")
        return

    render_section_header(st, "Original Recommendation")
    render_summary_grid(st, [
        ("Generated", format_timestamp(detail.get("generated_at"), "America/Los_Angeles")),
        ("Market price", f'{format_currency(detail.get("market_price"))}/MWh'),
        ("Score", f'{detail.get("opportunity_score", 0)}/100'),
        ("Recommendation", detail.get("recommendation") or "Not available"),
        ("Estimated profit", format_currency(detail.get("estimated_gross_profit"))),
        ("Break-even", f'{format_currency(detail.get("estimated_break_even_price"))}/MWh'),
        ("Engine version", detail.get("recommendation_engine_version") or "Not available"),
        ("Telemetry", "Available" if detail.get("telemetry_available") else "Unavailable"),
        ("Readiness", _label(detail.get("operational_readiness"))),
    ])
    st.markdown(str(detail.get("explanation") or "Explanation unavailable."))
    for driver in detail.get("drivers") or []:
        st.caption(f"Driver · {driver}")
    for risk in detail.get("risks") or []:
        st.caption(f"Risk · {risk}")
    comparison = detail.get("simulation_comparison")
    if comparison:
        st.caption("Explicitly linked simulation comparison")
        render_summary_grid(st, [
            ("Recommendation estimate", format_currency(comparison.get("recommendation_estimated_profit"))),
            ("Simulation estimate", format_currency(comparison.get("simulation_estimated_profit"))),
            ("Estimate difference", "Not available" if comparison.get("profit_difference") is None else format_currency(comparison.get("profit_difference"))),
        ])

    render_section_header(st, "Decision Path")
    timeline = detail.get("decision_timeline") or []
    if timeline:
        st.dataframe([{
            "Time": format_timestamp(item.get("timestamp"), "America/Los_Angeles"),
            "Event": _label(item.get("event")),
            "Attribution": item.get("attribution") or "system",
        } for item in timeline], width="stretch", hide_index=True)
    else:
        st.caption("No persisted decision events are available.")

    render_section_header(st, "Outcome")
    outcome = detail.get("outcome") or {}
    estimated = outcome.get("estimated") or {}
    realized = outcome.get("realized") or {}
    variance = outcome.get("variance") or {}
    render_summary_grid(st, [
        ("Status", _label(outcome.get("status"))),
        ("Estimated revenue", format_currency(estimated.get("revenue"))),
        ("Realized revenue", "Not available" if realized.get("revenue") is None else format_currency(realized.get("revenue"))),
        ("Estimated cost", format_currency(estimated.get("charging_cost"))),
        ("Realized cost", "Not available" if realized.get("charging_cost") is None else format_currency(realized.get("charging_cost"))),
        ("Estimated profit", format_currency(estimated.get("profit"))),
        ("Realized profit", "Not available" if realized.get("profit") is None else format_currency(realized.get("profit"))),
        ("Profit variance", "Not available" if (variance.get("profit") or {}).get("absolute") is None else format_currency(variance["profit"]["absolute"])),
    ])
