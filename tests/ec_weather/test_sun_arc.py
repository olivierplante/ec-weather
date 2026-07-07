"""Tests for the sun-arc metric cell (Claude Design handoff, commit 3 +
design-polish round).

One combined cell (not separate sunrise/sunset cells), drawn as ONE continuous
day/night loop:
  - dashed base arc AND a fainter below-horizon dip guide are both always
    drawn in arc mode; a solid "spent" trail overlays the elapsed part
  - dot rides the top arc by day (amber) and the dip by night (grey)
  - caption is ONLY the countdown ("sets in 9h 46m" / "sunrise in 7h 5m")
  - 12h/24h respects hass.locale.time_format
  - no sunrise/sunset published (far north) → "Sun up all day" (dot parked on
    a solid lit arc) or "Polar night" (dot resting in the dip); times hidden,
    no sublines
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


def _current_section() -> str:
    source = CARD_JS.read_text()
    start = source.find("_renderCurrent() {")
    end = source.find("_renderHourly() {", start)
    assert start != -1 and end != -1
    return source[start:end]


class TestArc:
    def test_arc_svg_geometry(self):
        """The design's arc: ellipse rx=72 ry=21 from (12,26) to (156,26)."""
        assert "A72,21" in _current_section()

    def test_dip_guide_geometry(self):
        """The below-horizon dip is a shallower rx=72 ry=13 guide, always
        drawn in arc mode so the whole loop is visible."""
        assert "A72,13" in _current_section()

    def test_sun_dot_positioned_by_loop_model(self):
        """Dot coordinates come from sunLoopModel (vitest-covered): day
        fraction on the top arc, night fraction on the dip."""
        assert "sunLoopModel(" in _current_section()

    def test_spent_trail_overlay(self):
        """A solid trail overlays the traveled part of the loop — amber over
        the day arc, grey (muted) over the night dip."""
        section = _current_section()
        assert 'opacity="0.55"' in section  # day trail
        assert 'opacity="0.5"' in section   # night trail

    def test_sunrise_sunset_icons(self):
        section = _current_section()
        assert "mdi:weather-sunset-up" in section
        assert "mdi:weather-sunset-down" in section

    def test_caption_localized(self):
        section = _current_section()
        assert "'sunriseIn'" in section
        assert "'sunsetIn'" in section

    def test_caption_countdown_plus_daylight(self):
        """User feedback on the polish round: keep the countdown ('sets in
        1h 26m') but bring back the daylight duration after it."""
        section = _current_section()
        assert "'ofDaylight'" in section
        assert "daylightMin" in section

    def test_sunset_key_in_both_languages(self):
        source = CARD_JS.read_text()
        en_block = source[source.find("en: {"):source.find("fr: {")]
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        assert "sunsetIn:" in en_block
        assert "sunsetIn:" in fr_block

    def test_duration_format_follows_design(self):
        """EN '9h 46m' (minutes-only '46m'); FR '9 h 46' with NO zero-padding
        and NO trailing minutes unit — the DC's fmtDur, exactly."""
        section = _current_section()
        assert "' h '" in section  # FR hour separator
        assert "padStart" not in section

    def test_clock_preference_respected(self):
        assert "use24Hour(" in _current_section()


class TestPolarStates:
    def test_sun_up_all_day(self):
        assert "'sunUpAllDay'" in _current_section()

    def test_polar_night(self):
        assert "'polarNight'" in _current_section()

    def test_chosen_by_sun_above_horizon(self):
        section = _current_section()
        assert "sun.sun" in section

    def test_mode_via_latitude_gated_helper(self):
        """Polar states only at polar latitudes (sunCellMode, vitest-covered):
        transient rise/set outages at 45°N hide the cell instead."""
        section = _current_section()
        assert "sunCellMode(" in section
        assert "latitude" in section

    def test_polar_sublines_retired(self):
        """The new spec shows only the cap — the 'no sunset today' /
        'sun below the horizon' sublines (and their keys) are gone."""
        source = CARD_JS.read_text()
        assert "noSunset" not in source
        assert "sunBelowHorizon" not in source


class TestPolarI18n:
    def test_polar_keys_in_both_languages(self):
        source = CARD_JS.read_text()
        en_block = source[source.find("en: {"):source.find("fr: {")]
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        for key in ("sunUpAllDay", "polarNight"):
            assert f"{key}:" in en_block, f"EN key {key} missing"
            assert f"{key}:" in fr_block, f"FR key {key} missing"

    def test_of_daylight_key_in_both_languages(self):
        source = CARD_JS.read_text()
        en_block = source[source.find("en: {"):source.find("fr: {")]
        fr_start = source.find("fr: {")
        fr_block = source[fr_start:source.find("\n};", fr_start)]
        assert "ofDaylight:" in en_block
        assert "ofDaylight:" in fr_block
