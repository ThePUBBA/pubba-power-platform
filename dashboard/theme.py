"""PUBBA Power light and dark presentation tokens."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    mode: str
    bg_page: str
    bg_sidebar: str
    bg_surface: str
    bg_surface_secondary: str
    text_primary: str
    text_secondary: str
    text_muted: str
    border_default: str
    border_strong: str
    input_bg: str
    hover_bg: str
    shadow: str


THEMES = {
    "dark": ThemeTokens(
        "dark", "#080A09", "#080808", "#171817", "#111311",
        "#FFFFFF", "#B5B7B6", "#8F9491", "#303331", "#3B403D",
        "#171817", "#1D211F", "rgba(0, 0, 0, .24)",
    ),
    "light": ThemeTokens(
        "light", "#F4F6F5", "#FFFFFF", "#FFFFFF", "#ECEFEE",
        "#111312", "#555B58", "#737A76", "#D8DDDA", "#BFC6C2",
        "#FFFFFF", "#E8ECEA", "rgba(17, 19, 18, .08)",
    ),
}

ACCENT = "#44FFBB"
ACCENT_FOREGROUND = "#000000"

PREFERENCE_KEY = "pubba_theme"
PREFERENCES = ("System", "Light", "Dark")


def normalize_preference(value: object) -> str:
    candidate = str(value or "system").strip().lower()
    return candidate if candidate in {"system", "light", "dark"} else "system"


def theme_preference(st) -> str:
    """Return the URL/session preference used by the visible selector."""
    query_value = st.query_params.get(PREFERENCE_KEY)
    preference = normalize_preference(
        query_value or st.session_state.get(PREFERENCE_KEY)
    )
    st.session_state[PREFERENCE_KEY] = preference
    return preference


def resolved_theme(st, preference: str = "system") -> ThemeTokens:
    """Return Streamlit's browser-resolved Light/Dark/System theme."""
    preference = normalize_preference(preference)
    if preference in {"light", "dark"}:
        return THEMES[preference]
    try:
        mode = str(st.context.theme.type or "dark").lower()
    except (AttributeError, RuntimeError):
        mode = "dark"
    return THEMES.get(mode, THEMES["dark"])


def render_theme_selector(st, preference: str) -> None:
    """Render a compact accessible selector and persist it in URL/localStorage."""
    st.sidebar.markdown(
        '<div class="pubba-theme-label">Appearance</div>',
        unsafe_allow_html=True,
    )
    buttons = "".join(
        f'<button type="button" data-theme="{option.lower()}" '
        f'class="{"selected" if option.lower() == preference else ""}" '
        f'aria-pressed="{str(option.lower() == preference).lower()}">{option}</button>'
        for option in PREFERENCES
    )
    st.sidebar.iframe(
        f"""
        <!doctype html>
        <html class="{preference}"><head><style>
        :root {{ color-scheme: dark; --surface:#111311; --text:#FFFFFF; --border:#303331; }}
        html.light {{ color-scheme: light; --surface:#ECEFEE; --text:#111312; --border:#D8DDDA; }}
        @media (prefers-color-scheme: light) {{
          html.system {{ color-scheme: light; --surface:#ECEFEE; --text:#111312; --border:#D8DDDA; }}
        }}
        html, body {{ margin:0; padding:0; overflow:hidden; background:transparent; }}
        .themes {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }}
        button {{
          min-width:0; min-height:40px; border:1px solid var(--border); border-radius:10px;
          background:var(--surface); color:var(--text); font:16px Inter,Arial,sans-serif;
          cursor:pointer; transition:border-color .15s ease, box-shadow .15s ease;
        }}
        button:hover {{ border-color:#44FFBB; }}
        button:focus-visible {{ outline:2px solid #44FFBB; outline-offset:2px; }}
        button.selected {{ border-color:#44FFBB; box-shadow:inset 0 0 0 1px #44FFBB; }}
        </style></head><body><div class="themes" role="group" aria-label="Appearance theme">
        {buttons}
        </div><script>
        (() => {{
          const key = "pubba-theme-preference";
          const current = "{preference}";
          const apply = (choice) => {{
            const parentUrl = new URL(window.parent.location.href);
            parentUrl.searchParams.set("{PREFERENCE_KEY}", choice);
            window.parent.localStorage.setItem(key, choice);
            const nativeKey = `stActiveTheme-${{window.parent.location.pathname}}-v2`;
            const nativeValue = choice.charAt(0).toUpperCase() + choice.slice(1);
            window.parent.localStorage.setItem(nativeKey, JSON.stringify(nativeValue));
            window.parent.location.assign(parentUrl.toString());
          }};
          document.querySelectorAll("button[data-theme]").forEach((button) => {{
            button.addEventListener("click", () => apply(button.dataset.theme));
          }});
          try {{
            const parentUrl = new URL(window.parent.location.href);
            const saved = window.parent.localStorage.getItem(key);
            if (!parentUrl.searchParams.has("{PREFERENCE_KEY}") && saved &&
                ["system", "light", "dark"].includes(saved)) {{
              parentUrl.searchParams.set("{PREFERENCE_KEY}", saved);
              window.parent.location.replace(parentUrl.toString());
              return;
            }}
            window.parent.localStorage.setItem(key, current);
            const nativeKey = `stActiveTheme-${{window.parent.location.pathname}}-v2`;
            const nativeValue = current.charAt(0).toUpperCase() + current.slice(1);
            let savedNative = null;
            try {{
              savedNative = JSON.parse(window.parent.localStorage.getItem(nativeKey));
            }} catch (_) {{ /* Replace malformed theme state below. */ }}
            if (savedNative !== nativeValue) {{
              window.parent.localStorage.setItem(nativeKey, JSON.stringify(nativeValue));
              window.parent.location.reload();
            }}
          }} catch (_) {{ /* URL/session persistence remains available. */ }}
        }})();
        </script></body></html>
        """,
        height=48,
        tab_index=0,
    )
