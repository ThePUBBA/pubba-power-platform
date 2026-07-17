"""Reusable presentation components for the PUBBA Power console."""

from html import escape


def install_console_theme(st) -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap');

        :root {
            --font-display: "Bebas Neue", "Arial Narrow", Arial, sans-serif;
            --font-body: Inter, Arial, Helvetica, sans-serif;
            --pubba-accent: #44FFBB;
            --pubba-bg: #000000;
            --pubba-surface: #0F0F0F;
            --pubba-card: #171717;
            --pubba-text: #FFFFFF;
            --pubba-muted: #A7A7A7;
            --pubba-border: #2A2A2A;
            --pubba-danger: #FF6B6B;
            --pubba-radius: 14px;
        }
        html, body, [class*="css"] {
            color: var(--pubba-text);
            font-family: var(--font-body);
        }
        .stApp {
            background: var(--pubba-bg);
            color: var(--pubba-text);
            font-family: var(--font-body);
        }
        [data-testid="stAppViewContainer"] > .main {
            background: var(--pubba-bg);
        }
        .block-container {
            max-width: 1440px;
            padding: 3rem 2.25rem 5rem;
        }
        [data-testid="stHeader"] {
            background: rgba(0, 0, 0, .88);
            border-bottom: 1px solid rgba(42, 42, 42, .55);
        }
        #MainMenu, footer { visibility: hidden; }

        [data-testid="stSidebar"] {
            background: #080808;
            border-right: 1px solid var(--pubba-border);
        }
        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1.25rem;
        }
        [data-testid="stSidebar"] hr {
            border-color: var(--pubba-border);
            margin: 1.2rem 0;
        }
        .pubba-brand {
            padding: .35rem .15rem 1.5rem;
        }
        .pubba-brand-mark {
            display: inline-flex;
            align-items: center;
            gap: .65rem;
            color: var(--pubba-text);
            font-family: var(--font-display);
            font-size: 1.4rem;
            font-weight: 400;
            letter-spacing: .025em;
            line-height: 1;
        }
        .pubba-brand-bolt {
            width: 2rem;
            height: 2rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 10px;
            color: #000;
            background: var(--pubba-accent);
            box-shadow: 0 0 24px rgba(68, 255, 187, .14);
        }
        .pubba-brand-subtitle {
            color: var(--pubba-muted);
            font-size: .72rem;
            letter-spacing: .09em;
            margin-top: .65rem;
            text-transform: uppercase;
            font-family: var(--font-display);
        }
        [data-testid="stSidebar"] [role="radiogroup"] {
            gap: .35rem;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            border: 1px solid transparent;
            border-radius: 10px;
            padding: .62rem .7rem;
            transition: background .16s ease, border-color .16s ease;
            font-family: var(--font-display);
            font-size: 1rem;
            letter-spacing: .025em;
            text-transform: uppercase;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: #141414;
            border-color: var(--pubba-border);
        }
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: rgba(68, 255, 187, .08);
            border-color: rgba(68, 255, 187, .35);
            color: var(--pubba-accent);
        }
        .pubba-connection {
            display: flex;
            align-items: center;
            gap: .55rem;
            color: var(--pubba-muted);
            font-size: .76rem;
            padding: .65rem .15rem;
        }
        .pubba-connection-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--pubba-accent);
            box-shadow: 0 0 10px rgba(68, 255, 187, .65);
        }
        .pubba-connection.is-error .pubba-connection-dot {
            background: var(--pubba-danger);
            box-shadow: 0 0 10px rgba(255, 107, 107, .45);
        }

        .pubba-page-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            padding: .2rem 0 1.6rem;
            border-bottom: 1px solid var(--pubba-border);
            margin-bottom: 1.8rem;
        }
        .pubba-eyebrow {
            color: var(--pubba-accent);
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .12em;
            text-transform: uppercase;
            margin-bottom: .65rem;
            font-family: var(--font-display);
            font-weight: 400;
        }
        .pubba-title {
            color: var(--pubba-text);
            font-size: clamp(2rem, 4vw, 3rem);
            font-family: var(--font-display);
            line-height: 1;
            font-weight: 400;
            letter-spacing: .015em;
            margin: 0;
        }
        .pubba-description {
            color: var(--pubba-muted);
            font-size: .95rem;
            line-height: 1.55;
            margin-top: .7rem;
            max-width: 680px;
            font-family: var(--font-body);
        }
        .pubba-badge {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            white-space: nowrap;
            color: var(--pubba-accent);
            background: rgba(68, 255, 187, .07);
            border: 1px solid rgba(68, 255, 187, .28);
            border-radius: 999px;
            padding: .42rem .7rem;
            font-size: .72rem;
            font-family: var(--font-display);
            font-weight: 400;
            letter-spacing: .035em;
            text-transform: uppercase;
        }
        .pubba-badge::before {
            content: "";
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--pubba-accent);
        }
        .pubba-section {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 2.2rem 0 .9rem;
        }
        .pubba-section-title {
            color: var(--pubba-text);
            font-family: var(--font-display);
            font-size: 1.2rem;
            font-weight: 400;
            letter-spacing: .025em;
            line-height: 1.1;
            text-transform: uppercase;
        }
        .pubba-section-line {
            height: 1px;
            flex: 1;
            margin-left: 1rem;
            background: var(--pubba-border);
        }
        .pubba-kpi {
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-radius: var(--pubba-radius);
            padding: 1.1rem 1.15rem;
            min-height: 116px;
            box-shadow: 0 12px 32px rgba(0, 0, 0, .2);
            transition: border-color .18s ease, transform .18s ease;
        }
        .pubba-kpi:hover {
            border-color: #3A3A3A;
            transform: translateY(-1px);
        }
        .pubba-kpi-label {
            color: var(--pubba-muted);
            font-size: .7rem;
            font-family: var(--font-display);
            font-weight: 400;
            text-transform: uppercase;
            letter-spacing: .075em;
        }
        .pubba-kpi-value {
            color: var(--pubba-text);
            font-size: clamp(1.3rem, 2vw, 1.75rem);
            font-family: var(--font-display);
            line-height: 1.05;
            font-weight: 400;
            letter-spacing: .01em;
            margin-top: .8rem;
            overflow-wrap: anywhere;
        }
        .pubba-positive { border-top: 2px solid var(--pubba-accent); }
        .pubba-negative { border-top: 2px solid var(--pubba-danger); }
        .pubba-neutral { border-top: 2px solid #404040; }
        .pubba-meta {
            color: var(--pubba-muted);
            font-size: .78rem;
        }

        [data-testid="stForm"] {
            background: var(--pubba-surface);
            border: 1px solid var(--pubba-border);
            border-radius: 16px;
            padding: 1.25rem 1.25rem .65rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--pubba-border);
            border-radius: var(--pubba-radius);
        }
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        [data-testid="stDateInput"] [data-baseweb="input"] > div {
            background: var(--pubba-card) !important;
            border-color: var(--pubba-border) !important;
            border-radius: 10px !important;
        }
        [data-baseweb="input"] > div:focus-within,
        [data-baseweb="select"] > div:focus-within {
            border-color: var(--pubba-accent) !important;
            box-shadow: 0 0 0 2px rgba(68, 255, 187, .12) !important;
        }
        .stButton > button, .stFormSubmitButton > button {
            min-height: 2.65rem;
            border-radius: 10px;
            font-family: var(--font-display);
            font-size: 1rem;
            font-weight: 400;
            letter-spacing: .035em;
            text-transform: uppercase;
            border: 1px solid var(--pubba-border);
            transition: transform .15s ease, border-color .15s ease, opacity .15s ease;
        }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            color: #000 !important;
            background: var(--pubba-accent) !important;
            border-color: var(--pubba-accent) !important;
        }
        .stButton > button:hover, .stFormSubmitButton > button:hover {
            transform: translateY(-1px);
            border-color: var(--pubba-accent) !important;
        }
        .stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
            outline: 2px solid var(--pubba-accent);
            outline-offset: 2px;
        }
        .stButton > button:disabled, .stFormSubmitButton > button:disabled {
            opacity: .45;
            transform: none;
        }
        [data-testid="stAlert"] {
            border-radius: 12px;
            border: 1px solid var(--pubba-border);
            font-family: var(--font-body);
        }
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            border: 1px solid var(--pubba-border);
            border-radius: var(--pubba-radius);
            overflow: hidden;
            background: var(--pubba-card);
            font-family: var(--font-body);
        }
        [data-testid="stPlotlyChart"] {
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-radius: var(--pubba-radius);
            padding: .65rem;
        }
        hr { border-color: var(--pubba-border) !important; }
        small, .stCaption, [data-testid="stCaptionContainer"] {
            color: var(--pubba-muted) !important;
            font-family: var(--font-body) !important;
        }
        input, textarea, [data-baseweb="select"] {
            font-family: var(--font-body) !important;
        }
        [data-testid="stWidgetLabel"] p {
            font-family: var(--font-display);
            font-size: .95rem;
            letter-spacing: .02em;
        }
        @media (max-width: 768px) {
            .block-container { padding: 2rem 1rem 3rem; }
            .pubba-page-header { align-items: flex-start; flex-direction: column; }
            .pubba-kpi { min-height: 104px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand(st) -> None:
    st.sidebar.markdown(
        """
        <div class="pubba-brand">
          <div class="pubba-brand-mark">
            <span class="pubba-brand-bolt">⚡</span><span>PUBBA Power</span>
          </div>
          <div class="pubba-brand-subtitle">Operations Console</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_connection_status(st, label: str, *, connected: bool) -> None:
    state_class = "" if connected else " is-error"
    st.sidebar.markdown(
        f'<div class="pubba-connection{state_class}">'
        f'<span class="pubba-connection-dot"></span>{escape(label)}</div>',
        unsafe_allow_html=True,
    )


def render_page_header(
    st, title: str, description: str, *, badge: str | None = None
) -> None:
    badge_html = f'<span class="pubba-badge">{escape(badge)}</span>' if badge else ""
    st.markdown(
        '<div class="pubba-page-header"><div>'
        '<div class="pubba-eyebrow">PUBBA Power</div>'
        f'<h1 class="pubba-title">{escape(title)}</h1>'
        f'<div class="pubba-description">{escape(description)}</div>'
        f'</div>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def render_section_header(st, title: str) -> None:
    st.markdown(
        f'<div class="pubba-section"><div class="pubba-section-title">'
        f'{escape(title)}</div><div class="pubba-section-line"></div></div>',
        unsafe_allow_html=True,
    )


def render_kpi_card(st, label: str, value: str, *, tone: str = "neutral") -> None:
    safe_tone = tone if tone in {"positive", "negative", "neutral"} else "neutral"
    st.markdown(
        f'<div class="pubba-kpi pubba-{safe_tone}">'
        f'<div class="pubba-kpi-label">{escape(label)}</div>'
        f'<div class="pubba-kpi-value">{escape(value)}</div></div>',
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
    st.markdown(
        f'<span class="pubba-meta">Data freshness · {escape(value)}</span>',
        unsafe_allow_html=True,
    )
