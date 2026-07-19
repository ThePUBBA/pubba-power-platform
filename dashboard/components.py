"""Reusable presentation components for the PUBBA Power console."""

from html import escape


def install_console_theme(st, theme) -> None:
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
            --pubba-elevated: #1C1C1C;
            --pubba-border: #2F2F2F;
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
            min-height: 150px;
            margin-bottom: .9rem;
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
        .pubba-kpi-head { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
        .pubba-kpi-icon { color: var(--pubba-muted); font-size: 1rem; }
        .pubba-kpi-subtitle { color: var(--pubba-muted); font-size: .72rem; line-height: 1.4; margin-top: .65rem; }
        .pubba-positive { border-top: 2px solid var(--pubba-accent); }
        .pubba-negative { border-top: 2px solid var(--pubba-danger); }
        .pubba-neutral { border-top: 2px solid #404040; }
        .pubba-meta {
            color: var(--pubba-muted);
            font-size: .78rem;
        }
        .pubba-notice {
            display: flex;
            align-items: center;
            gap: .7rem;
            color: var(--pubba-text);
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-left: 3px solid var(--pubba-accent);
            border-radius: 12px;
            padding: .9rem 1rem;
            font-family: var(--font-body);
            font-size: .9rem;
            line-height: 1.5;
        }
        .pubba-notice-dot {
            width: 7px;
            height: 7px;
            flex: 0 0 7px;
            border-radius: 50%;
            background: var(--pubba-accent);
            box-shadow: 0 0 10px rgba(68, 255, 187, .35);
        }
        .pubba-summary-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .75rem;
            margin: .45rem 0 1rem;
        }
        .pubba-summary-item {
            min-width: 0;
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-radius: 12px;
            padding: .8rem .9rem;
        }
        .pubba-summary-label {
            color: var(--pubba-muted);
            font-family: var(--font-display);
            font-size: .68rem;
            letter-spacing: .06em;
            text-transform: uppercase;
        }
        .pubba-summary-value {
            color: var(--pubba-text);
            font-family: var(--font-display);
            font-size: 1.22rem;
            line-height: 1.1;
            margin-top: .35rem;
            overflow-wrap: anywhere;
        }
        .pubba-asset-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
            gap: .85rem;
            margin-top: .75rem;
        }
        .pubba-asset-card {
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-radius: var(--pubba-radius);
            padding: 1.1rem;
        }
        .pubba-asset-head {
            display: flex;
            justify-content: space-between;
            gap: .75rem;
            align-items: flex-start;
            padding-bottom: .75rem;
            border-bottom: 1px solid var(--pubba-border);
        }
        .pubba-asset-name {
            color: var(--pubba-text);
            font-family: var(--font-display);
            font-size: 1.25rem;
        }
        .pubba-asset-status {
            color: var(--pubba-accent);
            font-family: var(--font-display);
            font-size: .72rem;
            letter-spacing: .05em;
            text-transform: uppercase;
        }
        .pubba-asset-meta {
            color: var(--pubba-muted);
            font-size: .76rem;
            margin-top: .3rem;
        }
        .pubba-asset-metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: .75rem;
            margin-top: .9rem;
        }
        .pubba-soc { margin-top: .9rem; }
        .pubba-soc-head {
            display: flex;
            justify-content: space-between;
            color: var(--pubba-muted);
            font-size: .75rem;
            margin-bottom: .35rem;
        }
        .pubba-soc-track {
            height: .7rem;
            border: 1px solid var(--pubba-border);
            border-radius: 999px;
            background: #0b0b0b;
            overflow: hidden;
        }
        .pubba-soc-fill {
            height: 100%;
            background: var(--pubba-accent);
        }
        .pubba-asset-metric span { display: block; }
        .pubba-asset-metric-label {
            color: var(--pubba-muted);
            font-family: var(--font-display);
            font-size: .65rem;
            letter-spacing: .05em;
            text-transform: uppercase;
        }
        .pubba-asset-metric-value {
            color: var(--pubba-text);
            font-size: .86rem;
            margin-top: .2rem;
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
            color: #000 !important;
            background: var(--pubba-accent) !important;
            font-family: var(--font-display);
            font-size: 1rem;
            font-weight: 400;
            letter-spacing: .035em;
            text-transform: uppercase;
            border: 1px solid var(--pubba-accent);
            transition: transform .15s ease, border-color .15s ease, opacity .15s ease;
        }
        .stButton > button *, .stFormSubmitButton > button * {
            color: #000 !important;
        }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"],
        button[data-testid="stBaseButton-primary"] {
            color: #000 !important;
            background: var(--pubba-accent) !important;
            border-color: var(--pubba-accent) !important;
        }
        .stButton > button[kind="primary"] *,
        .stFormSubmitButton > button[kind="primary"] *,
        button[data-testid="stBaseButton-primary"] * {
            color: #000 !important;
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
        .pubba-status-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .75rem;
        }
        .pubba-status-item {
            background: var(--pubba-card);
            border: 1px solid var(--pubba-border);
            border-radius: 12px;
            padding: .85rem 1rem;
        }
        .pubba-status-meta { color: var(--pubba-muted); font-size: .7rem; line-height: 1.45; margin-top: .4rem; }
        .pubba-capability-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .75rem; }
        .pubba-capability { min-height: 175px; background: var(--pubba-card); border: 1px solid var(--pubba-border); border-radius: var(--pubba-radius); padding: 1rem; }
        .pubba-capability-title { font-family: var(--font-display); font-size: 1.05rem; letter-spacing: .025em; }
        .pubba-capability-status { color: var(--pubba-accent); font-size: .7rem; margin: .6rem 0; text-transform: uppercase; }
        .pubba-capability-copy { color: var(--pubba-muted); font-size: .76rem; line-height: 1.5; }
        .pubba-environment { color: #000; background: var(--pubba-accent); border-radius: 999px; padding: .28rem .55rem; font: .72rem var(--font-display); letter-spacing: .04em; text-transform: uppercase; }
        .pubba-live-dot { animation: pubbaPulse 1.8s ease-in-out infinite; }
        @keyframes pubbaPulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
        [data-testid="stExpander"] { background: var(--pubba-card); border-color: var(--pubba-border); border-radius: 12px; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-thumb { background: #353535; border-radius: 999px; }
        .pubba-status-name {
            color: var(--pubba-muted);
            font-family: var(--font-display);
            letter-spacing: .04em;
            text-transform: uppercase;
        }
        .pubba-status-value { color: var(--pubba-text); margin-top: .35rem; }
        .pubba-status-value::before { content: "●"; color: var(--pubba-danger); margin-right: .45rem; }
        .pubba-status-value.is-good::before { color: var(--pubba-accent); }
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
            .pubba-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .pubba-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .pubba-capability-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: {theme.mode};
            --bg-page: {theme.bg_page};
            --bg-sidebar: {theme.bg_sidebar};
            --bg-surface: {theme.bg_surface};
            --bg-surface-secondary: {theme.bg_surface_secondary};
            --text-primary: {theme.text_primary};
            --text-secondary: {theme.text_secondary};
            --text-muted: {theme.text_muted};
            --border-default: {theme.border_default};
            --border-strong: {theme.border_strong};
            --accent: #44FFBB;
            --accent-foreground: #000000;
            --button-primary: #44FFBB;
            --button-primary-hover: #44FFBB;
            --input-bg: {theme.input_bg};
            --focus-ring: #44FFBB;
            --pubba-bg: var(--bg-page);
            --pubba-surface: var(--bg-surface-secondary);
            --pubba-card: var(--bg-surface);
            --pubba-text: var(--text-primary);
            --pubba-muted: var(--text-muted);
            --pubba-elevated: var(--bg-surface-secondary);
            --pubba-border: var(--border-default);
        }}
        [data-testid="stHeader"] {{
            background: color-mix(in srgb, var(--bg-page) 92%, transparent);
            border-bottom-color: var(--border-default);
        }}
        [data-testid="stSidebar"] {{ background: var(--bg-sidebar); }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
            background: {theme.hover_bg};
        }}
        .pubba-kpi {{ box-shadow: 0 12px 32px {theme.shadow}; }}
        .pubba-kpi:hover {{ border-color: var(--border-strong); }}
        .pubba-neutral {{ border-top-color: var(--border-strong); }}
        .pubba-soc-track {{ background: var(--bg-surface-secondary); }}
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        [data-testid="stDateInput"] [data-baseweb="input"] > div {{
            background: var(--input-bg) !important;
            color: var(--text-primary) !important;
        }}
        [data-baseweb="input"] input,
        [data-baseweb="input"] textarea,
        [data-baseweb="select"] input,
        [data-baseweb="select"] span,
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input {{
            color: var(--text-primary) !important;
            -webkit-text-fill-color: var(--text-primary) !important;
        }}
        [data-baseweb="input"] input::placeholder,
        [data-testid="stTextInput"] input::placeholder {{
            color: var(--text-muted) !important;
            -webkit-text-fill-color: var(--text-muted) !important;
            opacity: 1;
        }}
        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] [role="radiogroup"] label,
        [data-testid="stSidebar"] [role="radiogroup"] label p {{
            color: var(--text-primary) !important;
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked),
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
            color: var(--accent) !important;
        }}
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
            color: var(--text-muted) !important;
        }}
        [data-testid="stSegmentedControl"] button,
        [data-testid="stButtonGroup"] button,
        [data-baseweb="button-group"] button,
        [data-testid="stSidebar"] [role="group"] button {{
            background: var(--bg-surface-secondary) !important;
            border-color: var(--border-default) !important;
            color: var(--text-primary) !important;
        }}
        [data-testid="stSegmentedControl"] button *,
        [data-testid="stButtonGroup"] button *,
        [data-baseweb="button-group"] button *,
        [data-testid="stSidebar"] [role="group"] button * {{
            color: var(--text-primary) !important;
        }}
        [data-testid="stSegmentedControl"] button[aria-pressed="true"],
        [data-testid="stButtonGroup"] button[aria-pressed="true"],
        [data-baseweb="button-group"] button[aria-pressed="true"],
        [data-testid="stSidebar"] [role="group"] button[aria-pressed="true"],
        [data-testid="stSidebar"] [role="group"] button[aria-checked="true"],
        [data-testid="stSidebar"] [role="group"] button[data-active="true"],
        [data-testid="stSidebar"] [role="group"] button[data-selected="true"] {{
            background: var(--bg-surface-secondary) !important;
            border-color: var(--accent) !important;
            box-shadow: inset 0 0 0 1px var(--accent) !important;
            color: var(--text-primary) !important;
        }}
        [data-testid="stSegmentedControl"] button[aria-pressed="true"] *,
        [data-testid="stButtonGroup"] button[aria-pressed="true"] *,
        [data-baseweb="button-group"] button[aria-pressed="true"] *,
        [data-testid="stSidebar"] [role="group"] button[aria-pressed="true"] *,
        [data-testid="stSidebar"] [role="group"] button[aria-checked="true"] *,
        [data-testid="stSidebar"] [role="group"] button[data-active="true"] *,
        [data-testid="stSidebar"] [role="group"] button[data-selected="true"] * {{
            color: var(--text-primary) !important;
        }}
        [data-testid="stSidebar"] [data-testid="stButton"] button,
        [data-testid="stSidebar"] .stButton > button {{
            color: var(--accent-foreground) !important;
        }}
        [data-testid="stSidebar"] [data-testid="stButton"] button *,
        [data-testid="stSidebar"] .stButton > button * {{
            color: var(--accent-foreground) !important;
        }}
        [data-baseweb="popover"], [role="listbox"], [role="dialog"] {{
            background: var(--bg-surface) !important;
            color: var(--text-primary) !important;
            border-color: var(--border-default) !important;
        }}
        [data-testid="stDataFrame"], [data-testid="stTable"],
        [data-testid="stPlotlyChart"], [data-testid="stExpander"] {{
            background: var(--bg-surface);
            color: var(--text-primary);
        }}
        ::-webkit-scrollbar-thumb {{ background: var(--border-strong); }}
        a, button, input, textarea, select, [tabindex]:not([tabindex="-1"]) {{
            accent-color: var(--accent);
        }}
        a:focus-visible, button:focus-visible, input:focus-visible,
        textarea:focus-visible, select:focus-visible,
        [tabindex]:not([tabindex="-1"]):focus-visible {{
            outline: 2px solid var(--focus-ring) !important;
            outline-offset: 2px !important;
        }}
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
    st, title: str, description: str, *, badge: str | None = None,
    environment: str | None = None,
) -> None:
    badge_html = f'<span class="pubba-badge">{escape(badge)}</span>' if badge else ""
    environment_html = f'<span class="pubba-environment">{escape(environment)}</span>' if environment else ""
    st.markdown(
        '<div class="pubba-page-header"><div>'
        '<div class="pubba-eyebrow">PUBBA Power</div>'
        f'<h1 class="pubba-title">{escape(title)}</h1>'
        f'<div class="pubba-description">{escape(description)}</div>'
        f'</div><div style="display:flex;gap:.55rem;align-items:center">{badge_html}{environment_html}</div></div>',
        unsafe_allow_html=True,
    )


def render_section_header(st, title: str) -> None:
    st.markdown(
        f'<div class="pubba-section"><div class="pubba-section-title">'
        f'{escape(title)}</div><div class="pubba-section-line"></div></div>',
        unsafe_allow_html=True,
    )


def render_kpi_card(
    st, label: str, value: str, *, tone: str = "neutral",
    subtitle: str = "", icon: str = "", tooltip: str = "",
) -> None:
    safe_tone = tone if tone in {"positive", "negative", "neutral"} else "neutral"
    st.markdown(
        f'<div class="pubba-kpi pubba-{safe_tone}">'
        f'<div class="pubba-kpi-head"><div class="pubba-kpi-label" title="{escape(tooltip)}">{escape(label)}</div>'
        f'<div class="pubba-kpi-icon">{escape(icon)}</div></div>'
        f'<div class="pubba-kpi-value">{escape(value)}</div>'
        f'<div class="pubba-kpi-subtitle">{escape(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def render_summary_grid(st, items: list[tuple[str, str]]) -> None:
    cards = "".join(
        '<div class="pubba-summary-item">'
        f'<div class="pubba-summary-label">{escape(label)}</div>'
        f'<div class="pubba-summary-value">{escape(value)}</div>'
        '</div>'
        for label, value in items
    )
    st.markdown(
        f'<div class="pubba-summary-grid">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_asset_cards(st, assets: list[dict]) -> None:
    cards = "".join(
        '<div class="pubba-asset-card">'
        '<div class="pubba-asset-head"><div>'
        f'<div class="pubba-asset-name">{escape(asset["name"])}</div>'
        f'<div class="pubba-asset-meta">{escape(asset["technology"])} · {escape(asset["location"])}</div>'
        f'</div><div class="pubba-asset-status">{escape(asset["status"])}</div></div>'
        + (
            '<div class="pubba-soc">'
            f'<div class="pubba-soc-head"><span>State of charge</span><span>{escape(asset["soc"]["label"])}</span></div>'
            f'<div class="pubba-soc-track" role="progressbar" aria-label="State of charge" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{asset["soc"]["value"]}">'
            f'<div class="pubba-soc-fill" style="width:{asset["soc"]["value"]}%"></div></div></div>'
            if asset.get("soc") else ''
        )
        + '<div class="pubba-asset-metrics">'
        + "".join(
            '<div class="pubba-asset-metric">'
            f'<span class="pubba-asset-metric-label">{escape(label)}</span>'
            f'<span class="pubba-asset-metric-value">{escape(value)}</span></div>'
            for label, value in asset["metrics"]
        )
        + '</div></div>'
        for asset in assets
    )
    st.markdown(f'<div class="pubba-asset-grid">{cards}</div>', unsafe_allow_html=True)


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


def render_notice(st, message: str) -> None:
    st.markdown(
        '<div class="pubba-notice"><span class="pubba-notice-dot"></span>'
        f'<span>{escape(message)}</span></div>',
        unsafe_allow_html=True,
    )


def render_refresh_countdown(st, seconds: int = 60, *, theme=None) -> None:
    safe_seconds = max(1, int(seconds))
    st.iframe(
        f"""
        <!doctype html>
        <html>
          <head>
            <style>
              html, body {{
                margin: 0;
                padding: 0;
                overflow: hidden;
                background: transparent;
                color: {getattr(theme, 'text_muted', '#A7A7A7')};
                font-family: Inter, Arial, Helvetica, sans-serif;
                font-size: 12px;
              }}
              body {{ text-align: right; line-height: 22px; }}
              strong {{ color: #44FFBB; font-weight: 700; }}
            </style>
          </head>
          <body>
            Next refresh in <strong id="pubba-count">{safe_seconds}s</strong>
            <script>
              let remaining = {safe_seconds};
              const counter = document.getElementById("pubba-count");
              window.setInterval(() => {{
                remaining = remaining <= 1 ? {safe_seconds} : remaining - 1;
                counter.textContent = `${{remaining}}s`;
              }}, 1000);
            </script>
          </body>
        </html>
        """,
        height=28,
        tab_index=-1,
    )


def render_system_status(st, statuses: list[tuple]) -> None:
    items = "".join(
        '<div class="pubba-status-item">'
        f'<div class="pubba-status-name">{escape(name)}</div>'
        f'<div class="pubba-status-value{" is-good" if healthy else ""}">{escape(value)}</div>'
        f'<div class="pubba-status-meta">{escape(meta if len(item) > 3 else "")}</div></div>'
        for item in statuses
        for name, value, healthy, meta in [(*item, "")[:4]]
    )
    st.markdown(f'<div class="pubba-status-grid">{items}</div>', unsafe_allow_html=True)


def render_capabilities(
    st,
    capabilities: list[tuple[str, str, str]],
    *,
    status: str = "Planned",
) -> None:
    cards = "".join(
        '<div class="pubba-capability">'
        f'<div class="pubba-capability-title">{escape(name)}</div>'
        f'<div class="pubba-capability-status">{escape(status)} · {escape(integration)}</div>'
        f'<div class="pubba-capability-copy">{escape(description)}</div></div>'
        for name, description, integration in capabilities
    )
    st.markdown(f'<div class="pubba-capability-grid">{cards}</div>', unsafe_allow_html=True)
