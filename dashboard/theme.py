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
    selected = st.sidebar.segmented_control(
        "Appearance",
        PREFERENCES,
        default=preference.title(),
        selection_mode="single",
        help="System follows your device appearance setting.",
        key="pubba_theme_selector",
    )
    chosen = normalize_preference(selected)
    if chosen != preference:
        st.session_state[PREFERENCE_KEY] = chosen
        st.query_params[PREFERENCE_KEY] = chosen
        st.rerun()
    st.iframe(
        f"""
        <!doctype html><html><body><script>
        (() => {{
          const key = "pubba-theme-preference";
          const current = "{preference}";
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
          }} catch (_) {{ /* URL/session persistence remains available. */ }}
        }})();
        </script></body></html>
        """,
        height=0,
        tab_index=-1,
    )
