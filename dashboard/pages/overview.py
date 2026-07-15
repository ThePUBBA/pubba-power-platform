"""Executive Overview Streamlit page."""

from __future__ import annotations

from datetime import date

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import (
    render_data_freshness,
    render_empty_state,
    render_error_state,
    render_kpi_card,
    render_section_header,
)
from dashboard.formatting import (
    as_decimal,
    format_currency,
    format_energy,
    format_power,
    format_spread,
    format_timestamp,
    format_trading_return,
)
from dashboard.state import DashboardStateError, custom_date_range, is_empty_summary


def _tone(value: object) -> str:
    number = as_decimal(value)
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _cards(st, cards: list[tuple[str, str, str]], columns: int = 3) -> None:
    for start in range(0, len(cards), columns):
        row = st.columns(columns)
        for column, (label, value, tone) in zip(row, cards[start:start + columns]):
            with column:
                render_kpi_card(st, label, value, tone=tone)


def render(st, client: Only1ApiClient) -> None:
    title, refresh = st.columns([5, 1])
    with title:
        st.title("Portfolio Overview")
    with refresh:
        st.button("Refresh", type="primary", use_container_width=True)

    control_a, control_b = st.columns([1, 2])
    with control_a:
        range_mode = st.selectbox("Summary range", ["Lifetime", "Custom"])
    with control_b:
        timezone_name = st.text_input(
            "Reporting timezone override",
            placeholder="Use portfolio default",
            help="Optional IANA timezone, for example America/Los_Angeles.",
        )

    start_at = end_at = None
    if range_mode == "Custom":
        start_col, end_col = st.columns(2)
        with start_col:
            start_date = st.date_input("Start date", value=date.today())
        with end_col:
            end_date = st.date_input("End date", value=date.today())
        if not timezone_name.strip():
            render_error_state(
                st, "A reporting timezone is required for a custom date range."
            )
            return
        try:
            start_at, end_at = custom_date_range(
                start_date, end_date, timezone_name
            )
        except DashboardStateError as exc:
            render_error_state(st, str(exc))
            return

    try:
        with st.spinner("Loading authoritative portfolio metrics…"):
            summary = client.get_portfolio_summary(
                start_at=start_at,
                end_at=end_at,
                timezone_name=timezone_name or None,
            )
    except DashboardApiError as exc:
        render_error_state(st, str(exc))
        return

    portfolio = summary["portfolio"]
    financial = summary["financial"]
    revenue = summary["period_revenue"]
    operations = summary["operations"]
    fleet = summary["fleet"]
    metadata = summary["metadata"]
    reporting_timezone = summary["period"]["timezone"]
    currency = portfolio["currency_code"]
    market = portfolio["default_market"]

    st.caption(
        f"{portfolio['name']}  ·  Market: {market}  ·  "
        f"Reporting timezone: {reporting_timezone}  ·  "
        f"Last refresh: {format_timestamp(metadata['generated_at'], reporting_timezone)}"
    )
    render_data_freshness(
        st,
        format_timestamp(
            metadata["data_freshness_at"],
            reporting_timezone,
            fallback="No operational updates",
        ),
    )
    if is_empty_summary(summary):
        render_empty_state(st)

    render_section_header(st, "Financial performance")
    _cards(st, [
        ("Total Portfolio Profit", format_currency(financial["total_portfolio_profit"], currency), _tone(financial["total_portfolio_profit"])),
        ("Gross Revenue", format_currency(financial["gross_revenue"], currency), "neutral"),
        ("Charging Cost", format_currency(financial["charging_cost"], currency), "neutral"),
        ("Net Profit", format_currency(financial["net_profit"], currency), _tone(financial["net_profit"])),
        ("Trading Return", format_trading_return(financial["trading_return"]), _tone(financial["trading_return"])),
        ("Weighted Average Spread", format_spread(financial["weighted_average_spread_per_mwh"], currency), _tone(financial["weighted_average_spread_per_mwh"])),
    ])

    render_section_header(st, "Current-period revenue")
    _cards(st, [
        ("Revenue Today", format_currency(revenue["today"], currency), _tone(revenue["today"])),
        ("Revenue This Week", format_currency(revenue["week"], currency), _tone(revenue["week"])),
        ("Revenue This Month", format_currency(revenue["month"], currency), _tone(revenue["month"])),
        ("Revenue This Quarter", format_currency(revenue["quarter"], currency), _tone(revenue["quarter"])),
        ("Revenue This Year", format_currency(revenue["year"], currency), _tone(revenue["year"])),
    ])

    render_section_header(st, "Operations")
    _cards(st, [
        ("Total Dispatches", f"{operations['total_dispatches']:,}", "neutral"),
        ("Purchased Energy", format_energy(operations["purchased_energy_mwh"]), "neutral"),
        ("Sold Energy", format_energy(operations["sold_energy_mwh"]), "neutral"),
        ("Energy Throughput", format_energy(operations["energy_throughput_mwh"]), "neutral"),
        ("Last Dispatch", format_timestamp(operations["last_dispatch_at"], reporting_timezone, fallback="No completed dispatches"), "neutral"),
    ])

    render_section_header(st, "Fleet")
    _cards(st, [
        ("Active Assets", f"{fleet['active_assets']:,}", "neutral"),
        ("Fleet Power Capacity", format_power(fleet["power_capacity_mw"]), "neutral"),
        ("Fleet Energy Capacity", format_energy(fleet["energy_capacity_mwh"]), "neutral"),
    ])

    st.divider()
    st.caption(
        f"Metric version {metadata['metric_version']}  ·  Currency {currency}  ·  "
        f"Reporting timezone {reporting_timezone}  ·  "
        f"Generated {format_timestamp(metadata['generated_at'], reporting_timezone)}  ·  "
        f"Data freshness {format_timestamp(metadata['data_freshness_at'], reporting_timezone, fallback='Not available')}"
    )
