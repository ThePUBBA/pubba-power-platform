from pathlib import Path
from types import SimpleNamespace

import plotly.graph_objects as go

from dashboard.charts import chart_palette, style_chart
from dashboard.theme import THEMES, normalize_preference, resolved_theme


def test_streamlit_config_defines_native_light_dark_and_system_capable_themes():
    config = Path(".streamlit/config.toml").read_text()

    assert '[theme.light]' in config
    assert '[theme.dark]' in config
    assert 'primaryColor = "#44FFBB"' in config
    assert 'backgroundColor = "#F4F6F5"' in config
    assert 'backgroundColor = "#080A09"' in config


def test_resolved_theme_uses_streamlit_browser_context_and_safe_dark_default():
    light = SimpleNamespace(context=SimpleNamespace(theme=SimpleNamespace(type="light")))
    unknown = SimpleNamespace(context=SimpleNamespace(theme=SimpleNamespace(type=None)))

    assert resolved_theme(light) is THEMES["light"]
    assert resolved_theme(unknown) is THEMES["dark"]
    assert resolved_theme(unknown, "light") is THEMES["light"]


def test_theme_preference_normalization_supports_three_visible_choices():
    assert normalize_preference("Light") == "light"
    assert normalize_preference("dark") == "dark"
    assert normalize_preference("System") == "system"
    assert normalize_preference("unsupported") == "system"


def test_light_chart_palette_has_readable_text_grid_and_tooltip_surface():
    palette = chart_palette("light")
    figure = style_chart(go.Figure(), title="Market", theme="light")

    assert palette["primary"] == "#111312"
    assert palette["grid"] == "#D8DDDA"
    assert figure.layout.font.color == "#111312"
    assert figure.layout.xaxis.gridcolor == "#D8DDDA"
    assert figure.layout.hoverlabel.bgcolor == "#FFFFFF"


def test_dark_chart_palette_preserves_command_center_character():
    palette = chart_palette("dark")

    assert palette["primary"] == "#FFFFFF"
    assert palette["surface"] == "#171817"
    assert palette["grid"] == "#303331"
