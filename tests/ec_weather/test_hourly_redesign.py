"""Tests for the redesigned hourly section (Claude Design handoff, commit 4 +
design-polish round).

Column order per hour (64px), top to bottom: day label (at day boundaries) →
time + condition icon (header) → temperature trend line (SVG) → temp +
feels-like + POP% cluster → accumulation water-fill zone. Alternating faint
tint per calendar day with a day label at each midnight. Horizontal scroll
with a right-edge fade hint.

Rules:
  - missing temp → gap in the curve + blank label, never snap to 0°
  - area fill under the curve only when every hour has a temperature
  - feels-like and POP% each ALWAYS reserve their cluster line (blank when
    absent) so the cluster height is constant
  - the water-fill zone renders only when ANY hour has a real amount (hasQty);
    POP alone lives in the cluster and never gates the fill
  - a dry hour in a wet window keeps an empty (invisible) vessel
  - missing per-hour icon → quiet dash
  - time labels respect the 12/24h preference
  - hours are NOT clickable
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _hourly_section() -> str:
    source = CARD_JS.read_text()
    start = source.find("_renderHourly() {")
    end = source.find("_renderDaily() {", start)
    assert start != -1 and end != -1
    return source[start:end]


def _strip_section() -> str:
    """The shared strip builder + its CSS/defaults.

    _renderHourly() is now a thin wrapper: it filters empty timesteps and calls
    buildHourlyStripHtml(), which owns the curve, bands, cluster, water-fill
    and their CSS. Markers that used to live inline in _renderHourly moved here;
    the region spans STRIP_CSS/STRIP_DEFAULTS/fmtHourLabel/buildHourlyStripHtml.
    """
    source = CARD_JS.read_text()
    start = source.find("const STRIP_CSS =")
    end = source.find("export function popupPeriodModel(", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestCurve:
    def test_svg_trend_line(self):
        section = _strip_section()
        assert "<svg" in section
        assert "--ecw-curve" in section

    def test_curve_geometry_via_shared_helper(self):
        """Gap handling, isolated-point detection and the area-fill rule live
        in buildHourlyCurve() (vitest-covered)."""
        assert "buildHourlyCurve(" in _strip_section()

    def test_isolated_points_render_as_dots(self):
        """A lone 'M' subpath strokes nothing — isolated points get circles."""
        section = _strip_section()
        assert "isolated" in section
        assert "<circle" in section

    def test_curve_stroke_temperature_gradient(self):
        """The line strokes a per-hour temperature gradient (same absolute
        scale as the daily range bars), not a flat --ecw-curve."""
        section = _strip_section()
        assert "ecs-curve-stroke" in section
        assert "url(#ecs-curve-stroke)" in section

    def test_empty_timesteps_filtered(self):
        """All-null hours (store rows mid-load) are skipped, not rendered as
        blank 64px columns. The filter stays in the _renderHourly wrapper."""
        assert "isEmptyTimestep(" in _hourly_section()


class TestClusterAndFill:
    def test_fill_zone_gated_on_real_amounts(self):
        """hasQty (any hour's rain+snow > 0) gates the water-fill zone; POP
        never does — a POP-only window renders no fill."""
        section = _strip_section()
        assert "hasQty" in section
        assert "hasPrecipBlock" not in section

    def test_pop_reserved_in_cluster(self):
        """POP% lives in the temp cluster on an always-reserved line."""
        section = _strip_section()
        assert "precipitation_probability" in section
        assert "--ecw-pop" in section
        assert "&nbsp;" in section

    def test_water_fill_vessel(self):
        """Fixed-height vessel per hour, fill scaled to the window's max
        (vitest covers the min-3/max-30 clamps and scaling)."""
        section = _strip_section()
        assert "ecs-vessel" in section
        assert "windowMaxQty" in section
        assert "vesselHeight: 30" in section

    def test_snow_stacked_above_rain(self):
        """Snow (lighter) sits on top of the rain fill, offset by its height."""
        section = _strip_section()
        assert "--ecw-snowbar" in section
        assert "bottom:' + rainH" in section

    def test_amount_units_compact(self):
        """Amount labels are compact with no space ('1mm 1cm')."""
        section = _strip_section()
        assert "fmtAmtUnit(" in section
        assert "+ ' mm'" not in section
        assert "+ ' cm'" not in section

    def test_no_divider_under_the_fill(self):
        """The old hairline baseline under the bars is gone (popup rule: no
        divider between cluster and fill zone)."""
        assert "ecs-barrow" not in _strip_section()


class TestDayBands:
    def test_alternating_day_tint(self):
        section = _strip_section()
        assert "dayCount % 2" in section
        assert "--ecw-tint" in section

    def test_day_label_at_midnight(self):
        """Label like 'SAT 1': weekday + date number."""
        section = _strip_section()
        assert "getDate()" in section

    def test_old_vertical_day_separator_gone(self):
        assert "hourly-day-sep" not in _strip_section()


class TestHourColumns:
    def test_missing_icon_quiet_dash(self):
        assert "missingIconHtml(" in _strip_section()

    def test_time_respects_clock_preference(self):
        assert "use24Hour(" in _strip_section()

    def test_feels_like_shown_when_different(self):
        section = _strip_section()
        assert "'FL '" in section

    def test_header_top_order_shared_with_popup(self):
        """Time + icon form the header in BOTH strips — the old per-caller
        bottom-row order option is retired."""
        assert "bottomRowOrder" not in CARD_JS.read_text()

    def test_not_clickable(self):
        """No click wiring in either the wrapper or the shared builder."""
        assert "addEventListener" not in _hourly_section()
        assert "addEventListener" not in _strip_section()


class TestScrollFade:
    def test_fade_removed_by_user_preference(self):
        """The right-edge gradient hint from the polish round was removed —
        the user found the transition distracting. Keep it out."""
        assert "hfade" not in CARD_JS.read_text()


class TestThemeIntegration:
    def test_uses_shared_tokens(self):
        assert "TOKEN_CSS" in _hourly_section()

    def test_theme_class_wrapper(self):
        assert "themeClass" in _hourly_section()
