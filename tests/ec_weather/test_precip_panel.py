"""Tests for the precipitation panel (Claude Design handoff, commit 3).

The panel lives inside the current section's hero row. Rules:
  - header: title + POP% when today is wet; "None expected" when today is dry
    (and the Today row collapses entirely)
  - Today row uses the SAME dailyPrecip() as the daily column (never diverge)
  - Yesterday row: sensor absent → row omitted; opted-in but unpublished →
    "No data"; dry past day → "None" (past tense); split stations → rain+snow
    chips; combined stations → water-only chip (mm) + explanatory tooltip
  - bars scale to the largest row via liquid equivalent (1 cm snow ~ 1 mm),
    minimum segment width so trace amounts stay visible, capped at 100%
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _current_section() -> str:
    source = CARD_JS.read_text()
    start = source.find("_renderCurrent() {")
    end = source.find("_renderHourly() {", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestPanelStructure:
    def test_panel_container(self):
        assert "ppanel" in _current_section()

    def test_title_localized(self):
        assert "'precipTitle'" in _current_section()

    def test_today_row_uses_shared_daily_precip(self):
        """Same source as the daily column so they never diverge."""
        assert "dailyPrecip(" in _current_section()

    def test_dry_today_header_none_expected(self):
        assert "'noneExpected'" in _current_section()

    def test_header_decision_via_shared_helper(self):
        """The header branch order lives in precipPanelHead() (vitest-covered):
        a real POP always beats the 'None expected' claim."""
        assert "precipPanelHead(" in _current_section()

    def test_today_row_label(self):
        assert "'todayForecast'" in _current_section()


class TestYesterdayBranches:
    def test_reads_yesterday_sensors(self):
        section = _current_section()
        assert "sensor.ec_yesterday_precipitation" in section
        assert "sensor.ec_yesterday_rain" in section
        assert "sensor.ec_yesterday_snow" in section

    def test_opted_out_row_omitted(self):
        """No sensor → no yesterday row at all (not a dash, not 'None')."""
        assert "ydayState" in _current_section()

    def test_unpublished_shows_no_data(self):
        section = _current_section()
        assert "published" in section
        assert "'noData'" in section

    def test_dry_past_day_shows_none(self):
        """Past tense 'None', NOT 'None expected'."""
        assert "'none'" in _current_section()

    def test_split_station_rain_and_snow(self):
        assert "'split'" in _current_section()

    def test_combined_station_water_only_with_tooltip(self):
        """Combined stations report melted equivalent — render as water (mm)
        with the existing explanatory tooltip."""
        section = _current_section()
        assert "yesterdayCombinedTooltip" in section
        assert "title=" in section


class TestBars:
    def test_liquid_equivalent_scaling(self):
        assert "liquidTotal(" in _current_section()

    def test_minimum_segment_width(self):
        """Trace amounts keep a visible sliver."""
        assert "Math.max(3" in _current_section()

    def test_rain_and_snow_chips(self):
        section = _current_section()
        assert "mdi:water" in section
        assert "mdi:snowflake" in section

    def test_units_compact_mm_and_cm(self):
        """Design audit: amounts are compact with NO space ('3mm', '5cm')
        everywhere — the panel chips go through fmtAmtUnit."""
        section = _current_section()
        assert "fmtAmtUnit(rain, 'mm')" in section
        assert "fmtAmtUnit(snow, 'cm')" in section
        assert "+ ' mm'" not in section
        assert "+ ' cm'" not in section


class TestTooltipText:
    def test_combined_tooltip_explains_water_equivalent(self):
        source = CARD_JS.read_text()
        lowered = source.lower()
        assert "combined" in lowered
        assert "water equivalent" in lowered
