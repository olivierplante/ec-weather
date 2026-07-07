"""Tests for the redesigned daily section (Claude Design handoff, commit 5).

Per row: day · dual icons (day colored by condition type, night dimmed) ·
POP% + accumulation · low · range bar · high.

Rules:
  - range bar positioned against the week's own min/max, colored by
    ABSOLUTE temperature (gradient tempColor(low) → tempColor(high))
  - single value (Tonight first period / dropped high after ~4 PM, or
    low == high) → a dot at that temp, the other side blank
  - isothermal week (min == max) → divide-by-zero guard, dots center
  - dry day → no precip column content
  - missing day icon → quiet dash; missing night icon → weather-night
  - day/hour click still opens the existing detail popup (lazy fetch kept)
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _source() -> str:
    return CARD_JS.read_text()


def _daily_section() -> str:
    source = _source()
    start = source.find("_renderDaily() {")
    end = source.find("_openDailyPopup(index) {", start)
    assert start != -1 and end != -1
    return source[start:end]


def _icon_color_fn() -> str:
    source = _source()
    start = source.find("function dailyIconColor")
    assert start != -1, "dailyIconColor helper must exist"
    end = source.find("\nfunction ", start + 1)
    return source[start:end if end != -1 else None]


class TestRows:
    def test_rows_replace_columns(self):
        section = _daily_section()
        assert "drow" in section
        assert "daily-col" not in section
        assert "daily-scroll" not in section

    def test_today_row_emphasized(self):
        assert "dtoday" in _daily_section()


class TestDualIcons:
    def test_day_and_night_icons(self):
        section = _daily_section()
        assert "dicons" in section
        assert "icon_code_night" in section

    def test_night_icon_fallback(self):
        assert "mdi:weather-night" in _daily_section()

    def test_day_icon_colored_by_type(self):
        assert "dailyIconColor(" in _daily_section()

    def test_missing_day_icon_quiet_dash(self):
        assert "missingIconHtml(" in _daily_section()


class TestIconColorHelper:
    def test_mix_before_snow(self):
        """snowy-rainy must resolve as mix (rain accent), not snow."""
        body = _icon_color_fn()
        assert body.find("snowy-rainy") < body.find("'snowy'")

    def test_accent_tokens(self):
        body = _icon_color_fn()
        assert "--ecw-rain" in body
        assert "--ecw-snow" in body
        assert "--ecw-sun" in body


class TestRangeBar:
    def test_week_min_max_scale(self):
        section = _daily_section()
        assert "Math.min.apply" in section
        assert "Math.max.apply" in section

    def test_gradient_by_absolute_temperature(self):
        section = _daily_section()
        assert "linear-gradient(90deg" in section
        assert "tempColor(" in section

    def test_geometry_via_shared_helper(self):
        """Span clamping (left+width <= 100), the isothermal guard and the
        single-value dot rule live in rangeBarGeometry() (vitest-covered)."""
        assert "rangeBarGeometry(" in _daily_section()

    def test_single_value_dot(self):
        section = _daily_section()
        assert "ddot" in section


class TestPrecipColumn:
    def test_uses_shared_daily_precip(self):
        assert "dailyPrecip(" in _daily_section()

    def test_pop_in_pop_color(self):
        assert "--ecw-pop" in _daily_section()

    def test_precip_column_always_reserved_on_wide(self):
        """User feedback on the polish round: the DC's dry-day column
        omission made range bars different lengths across rows. The column
        is ALWAYS emitted on wide (empty on dry days) so every bar shares
        one scale; only its CONTENT is wet-gated. The narrow float stays
        wet-only."""
        section = _daily_section()
        assert "isWet" in section
        assert "'<span class=\"dprecip\">'" in section


class TestPopupPreserved:
    def test_click_opens_popup(self):
        section = _daily_section()
        assert "addEventListener" in section
        assert "_openDailyPopup(" in section

    def test_popup_precompute_kept(self):
        assert "_dailyPopups" in _daily_section()

    def test_open_popup_update_path_kept(self):
        assert "_openPopupIndex" in _daily_section()


class TestNarrowLayout:
    """Mobile-tile reflow: drop the fixed precip column and float POP% +
    amounts centered just above that day's range bar (handoff Row layout).
    Pure CSS via a container query — the range bar stays the structural spine.
    """

    def test_container_query_context(self):
        section = _daily_section()
        assert "container-type: inline-size" in section
        assert "@container" in section

    def test_precip_rendered_as_column_and_float(self):
        section = _daily_section()
        # Wet-day precip is emitted twice: the fixed column AND the in-bar float.
        assert "dprecip" in section
        assert "dfloat" in section

    def test_temps_grouped(self):
        """low · range bar · high are one flex group so min/max always align."""
        assert "dtemps" in _daily_section()

    def test_narrow_bar_keeps_minimum_width(self):
        """DC .ecc.narrow .dbar{min-width:58px}: the range bar can't be
        squeezed to nothing by long labels on the narrow tile."""
        assert "min-width: 58px" in _daily_section()

    def test_float_metrics_match_the_dc(self):
        """.dprecipfloat metrics: gap 7, font-size 10, margin-bottom 5."""
        section = _daily_section()
        float_start = section.find(".dfloat {")
        float_rule = section[float_start:section.find("}", float_start)]
        assert "gap: 7px" in float_rule
        assert "font-size: 10px" in float_rule
        assert "margin-bottom: 5px" in float_rule


class TestThemeIntegration:
    def test_uses_shared_tokens(self):
        assert "TOKEN_CSS" in _daily_section()

    def test_theme_class_wrapper(self):
        assert "themeClass" in _daily_section()
