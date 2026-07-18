"""Server-side Streamlit OIDC session bridge to FastAPI identity verification."""

from __future__ import annotations

import os

from dashboard.api_client import DashboardApiError, Only1ApiClient


def _auth_mode() -> str:
    configured = os.getenv("OPERATOR_AUTH_MODE", "").strip().lower()
    if configured in {"off", "shadow", "enforce"}:
        return configured
    return "enforce" if os.getenv("OPERATOR_AUTH_REQUIRED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    } else "off"


def _identity_token(user: object) -> str | None:
    try:
        tokens = user.tokens
        for key in ("id", "access"):
            try:
                value = tokens[key]
            except (KeyError, TypeError):
                value = getattr(tokens, key, None)
            if value:
                return str(value).strip() or None
        return None
    except (AttributeError, KeyError, TypeError):
        return None


def _user_display_name(user: object) -> str:
    """Return a safe display label from Streamlit's verified OIDC claims."""
    for key in ("name", "email"):
        try:
            value = user[key]
        except (KeyError, TypeError):
            value = getattr(user, key, None)
        if value and str(value).strip():
            return str(value).strip()
    return "Authenticated user"


def configure_operator_identity(st, client: Only1ApiClient) -> dict | None:
    """Use only Streamlit's verified OIDC session token; never trust form claims."""
    try:
        user = st.user
        logged_in = bool(user.is_logged_in)
    except (AttributeError, KeyError, RuntimeError):
        user = None
        logged_in = False
    if not logged_in:
        st.markdown("PUBBA POWER")
        st.title("Sign in to PUBBA Power")
        if st.button("Sign in with Google", type="primary"):
            st.login()
        st.stop()
    st.sidebar.caption("Signed in as")
    st.sidebar.write(_user_display_name(user))
    if st.sidebar.button("Logout"):
        st.logout()
        st.stop()
    token = _identity_token(user)
    if not token:
        st.sidebar.caption("Operator identity · Token unavailable")
        st.error("The OIDC identity token is not available to the server.")
        st.stop()
    client.set_operator_access_token(token)
    try:
        operator = client.get_current_operator()
    except DashboardApiError as exc:
        st.sidebar.caption("Operator identity · Access denied")
        if _auth_mode() == "shadow":
            return None
        st.error(f"Operator access is unavailable — {exc}")
        st.stop()
    st.sidebar.markdown(f'**{operator["display_name"]}**')
    st.sidebar.caption(f'Role · {str(operator["role"]).title()}')
    return operator


def can(operator: dict | None, *roles: str) -> bool:
    return bool(operator and operator.get("status") == "active" and operator.get("role") in roles)
