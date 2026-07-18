"""Minimal admin-only operator authorization management."""

from dashboard.api_client import DashboardApiError, Only1ApiClient
from dashboard.components import render_page_header, render_section_header


ROLES = ["viewer", "operator", "approver", "admin"]


def render(st, client: Only1ApiClient, operator: dict | None = None) -> None:
    render_page_header(
        st, "Operator Access", "OIDC identities and PUBBA role assignments.",
        badge="Admin only", environment="Production",
    )
    if not operator or operator.get("role") != "admin":
        st.error("Administrator access is required.")
        return
    try:
        records = client.get_operators()
    except DashboardApiError as exc:
        st.warning(f"Operator access records are unavailable — {exc}")
        return
    render_section_header(st, "Operators")
    st.dataframe([{
        "Name": item.get("display_name"), "Email": item.get("email"),
        "Role": str(item.get("role") or "").title(),
        "Status": str(item.get("status") or "").title(),
    } for item in records], width="stretch", hide_index=True)

    render_section_header(st, "Provision Operator Profile")
    st.caption("The identity must already exist in the configured OIDC provider. PUBBA Power never handles passwords.")
    with st.form("create_operator"):
        auth_subject = st.text_input("OIDC subject")
        email = st.text_input("Email")
        display_name = st.text_input("Display name")
        role = st.selectbox("Role", ROLES)
        submitted = st.form_submit_button("Create Operator Profile", type="primary")
    if submitted:
        try:
            client.create_operator({
                "auth_subject": auth_subject, "email": email,
                "display_name": display_name, "role": role, "status": "active",
            })
            st.success("Operator profile created. Credentials remain managed by the OIDC provider.")
            st.rerun()
        except DashboardApiError as exc:
            st.error(f"Operator profile could not be created — {exc}")

    if records:
        render_section_header(st, "Change Access")
        selected = st.selectbox(
            "Operator", [str(item["id"]) for item in records],
            format_func=lambda value: next(
                f'{item.get("display_name")} · {item.get("email")}'
                for item in records if str(item["id"]) == value
            ),
        )
        current = next(item for item in records if str(item["id"]) == selected)
        role = st.selectbox("Assigned role", ROLES, index=ROLES.index(str(current["role"])))
        status = st.selectbox("Status", ["active", "inactive"], index=0 if current.get("status") == "active" else 1)
        confirmed = st.checkbox("Confirm access change")
        if st.button("Update Operator Access", disabled=not confirmed):
            try:
                client.update_operator(selected, {"role": role, "status": status})
                st.success("Operator access updated and audited.")
                st.rerun()
            except DashboardApiError as exc:
                st.error(f"Operator access could not be updated — {exc}")

        render_section_header(st, "Portfolio Assignment")
        try:
            portfolios = client.get_authorized_portfolios()
        except DashboardApiError as exc:
            st.caption(f"Portfolio assignments are unavailable — {exc}")
            portfolios = []
        if portfolios:
            portfolio_options = {str(item["id"]): item for item in portfolios}
            portfolio_id = st.selectbox(
                "Portfolio", list(portfolio_options),
                format_func=lambda value: str(
                    portfolio_options[value].get("name")
                    or portfolio_options[value].get("code") or value
                ),
            )
            override = st.selectbox(
                "Portfolio role", ["Use global role", "viewer", "operator", "approver"]
            )
            active = st.checkbox("Portfolio access active", value=True)
            assignment_confirmed = st.checkbox("Confirm portfolio access change")
            if st.button("Update Portfolio Access", disabled=not assignment_confirmed):
                try:
                    client.update_operator_portfolio_access(selected, {
                        "portfolio_id": portfolio_id,
                        "role_override": None if override == "Use global role" else override,
                        "active": active,
                    })
                    st.success("Portfolio access updated and audited transactionally.")
                    st.rerun()
                except DashboardApiError as exc:
                    st.error(f"Portfolio access could not be updated — {exc}")
