"""Small reusable Streamlit presentation components."""


def install_console_theme(st) -> None:
    st.markdown(
        """
        <style>
        .stApp { background-color: #0b1118; color: #e8edf2; }
        [data-testid="stSidebar"] { background-color: #111a24; }
        .o1-kpi { background:#121c27; border:1px solid #263442; border-radius:8px;
                  padding:14px 16px; min-height:104px; }
        .o1-label { color:#94a3b8; font-size:.78rem; text-transform:uppercase;
                    letter-spacing:.05em; }
        .o1-value { color:#f8fafc; font-size:1.45rem; font-weight:650; margin-top:8px; }
        .o1-positive { border-left:3px solid #22c55e; }
        .o1-negative { border-left:3px solid #ef4444; }
        .o1-neutral { border-left:3px solid #38bdf8; }
        .o1-meta { color:#94a3b8; font-size:.8rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(st, title: str) -> None:
    st.markdown(f"### {title}")


def render_kpi_card(st, label: str, value: str, *, tone: str = "neutral") -> None:
    safe_tone = tone if tone in {"positive", "negative", "neutral"} else "neutral"
    st.markdown(
        f'<div class="o1-kpi o1-{safe_tone}"><div class="o1-label">{label}</div>'
        f'<div class="o1-value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def render_error_state(st, message: str) -> None:
    st.error(f"Portfolio data unavailable — {message}")
    st.caption("Use Refresh after the backend issue is resolved.")


def render_empty_state(st) -> None:
    st.info(
        "No active assets or completed operational dispatch history is available yet. "
        "Assets can be created through the existing API-supported workflow."
    )


def render_data_freshness(st, value: str) -> None:
    st.markdown(f'<span class="o1-meta">Data freshness: {value}</span>', unsafe_allow_html=True)

