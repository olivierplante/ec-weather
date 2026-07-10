"""Tests for the redesigned current section (Claude Design handoff, commit 3).

Layout: hero row (condition icon + big temp + "condition · feels like N°",
beside the precipitation panel) over a metric bar
(humidity · wind · AQHI · UV · sun-arc).

Source-text assertions on the bundled card JS (the established pattern).
Behavioural rules verified here:
  - missing temp → "—°"; feels-like dropped when absent OR equal to temp
  - missing condition icon → quiet dimmed dash (not a cloud, not a "?")
  - humidity cell removed when null; remaining metric cells reflow
  - wind 0 → "Calm" (no direction); no gust data → gust line hidden
  - AQHI/UV are metric cells colored by risk, hidden entirely when absent
  - narrow tiles reflow via container query
  - the old header/details-grid layout is fully gone
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _current_section() -> str:
    """Return the _renderCurrent method body (the definition, not call sites)."""
    source = CARD_JS.read_text()
    start = source.find("_renderCurrent() {")
    end = source.find("_renderHourly() {", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestHero:
    def test_hero_row_container(self):
        assert "herorow" in _current_section()

    def test_missing_temp_renders_em_dash_degree(self):
        assert "—°" in _current_section()

    def test_missing_icon_uses_quiet_dash(self):
        assert "missingIconHtml(" in _current_section()

    def test_feels_like_dropped_when_equal(self):
        """feels === temp → clause omitted entirely."""
        section = _current_section()
        assert "!== tVal" in section

    def test_condition_text_escaped(self):
        assert "escapeHtml" in _current_section()


class TestOldLayoutGone:
    def test_no_details_grid(self):
        assert "details-grid" not in _current_section()

    def test_no_pop_stack(self):
        """The old today-precip stack is replaced by the precip panel."""
        assert "pop-stack" not in _current_section()

    def test_no_standalone_daylight_cell(self):
        assert "daylightLabel" not in _current_section()

    def test_no_aqhi_quiet_line(self):
        """AQHI moved from a hero line to a metric-bar cell."""
        assert "aqhi-line" not in _current_section()


class TestMetricBar:
    def test_metric_bar_with_cells(self):
        section = _current_section()
        assert "mbar" in section
        assert "mcell" in section

    def test_humidity_cell_conditional(self):
        """Humidity null → cell not rendered → flex reflow."""
        section = _current_section()
        # Entity ids are resolved by role now (see LEGACY_ENTITY_IDS + the
        # ec_weather/entities command); the section reads the 'humidity' role.
        assert "entityIdFor('humidity')" in section
        assert "humidity !== null" in section or "humidity != null" in section

    def test_wind_calm(self):
        section = _current_section()
        assert "'calm'" in section

    def test_wind_cell_state_via_helper(self):
        """null wind hides the cell (windCellState, vitest-covered) — 'Calm'
        is a measurement, never a fallback for missing data."""
        assert "windCellState(" in _current_section()

    def test_gust_line_hidden_without_data(self):
        section = _current_section()
        assert "gust" in section.lower()

    def test_wind_headline_carries_unit(self):
        """Design audit: headline is speed+unit ('12 km/h') so it stays
        unambiguous on the narrow-tile wrap."""
        assert "' km/h'" in _current_section()

    def test_wind_secondary_joins_dir_and_gusts(self):
        """Secondary line is 'NW · gusts 29' — direction and gusts joined by
        a middot, either part alone when the other is absent (vitest covers
        the full matrix)."""
        section = _current_section()
        assert "' · '" in section or "' \\u00b7 '" in section

    def test_aqhi_cell_uses_risk_buckets(self):
        section = _current_section()
        assert "aqhiColor(" in section
        assert "'aqhiLabel'" in section

    def test_uv_cell_uses_risk_buckets(self):
        section = _current_section()
        assert "uvColor(" in section

    def test_aqhi_uv_hidden_when_absent(self):
        """Color helper returns null when value absent → cell skipped."""
        section = _current_section()
        assert "aqhiCol" in section and "uvCol" in section

    def test_no_aqhi_threshold_gate(self):
        """Old rule (shown only >= 4) is replaced by always-shown-when-present."""
        assert "aqhi >= 4" not in _current_section()


class TestRenderGating:
    def test_watch_list_exists(self):
        """Roles the section displays but must not gate availability on still
        need to trigger re-renders when they change. The watch list is a role
        list now (resolved to ids via the entity-discovery command)."""
        source = CARD_JS.read_text()
        assert "SECTION_WATCH_ROLES" in source
        watch_start = source.find("const SECTION_WATCH_ROLES")
        watch_block = source[watch_start:source.find("};", watch_start)]
        assert "'daily_forecast'" in watch_block
        assert "'sunrise'" in watch_block
        assert "'air_quality'" in watch_block

    def test_change_detection_uses_watch_list(self):
        source = CARD_JS.read_text()
        start = source.find("set hass(")
        section = source[start:source.find("getCardSize(", start)]
        assert "SECTION_WATCH_ROLES" in section


class TestNarrowReflow:
    def test_container_query(self):
        section = _current_section()
        assert "@container" in section

    def test_host_is_size_container(self):
        assert "container-type: inline-size" in _current_section()


class TestThemeIntegration:
    def test_uses_shared_tokens(self):
        assert "TOKEN_CSS" in _current_section()

    def test_theme_class_wrapper(self):
        assert "themeClass" in _current_section()
