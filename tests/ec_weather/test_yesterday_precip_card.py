"""Tests for the yesterday's-precipitation card rendering (issue #9, Part B).

Source-text assertions on the bundled card JS (the established pattern for
card tests). Since the redesign, yesterday renders as a precipitation-panel
row (see test_precip_panel.py for the full branch matrix):

  - Unpublished (null) → "No data" status
  - Dry (0) → "None" status (past tense)
  - Split station → rain (mm) + snow (cm) chips
  - Combined station → single water chip whose row carries a `title` tooltip
    mentioning "combined" and "water equivalent"
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


class TestYesterdayPrecipCard:
    def test_reads_yesterday_sensors(self):
        source = CARD_JS.read_text()
        assert "sensor.ec_yesterday_precipitation" in source
        assert "sensor.ec_yesterday_rain" in source
        assert "sensor.ec_yesterday_snow" in source

    def test_distinguishes_published_from_dry(self):
        """Card must branch on the published attribute, not just value."""
        source = CARD_JS.read_text()
        assert "published" in source, (
            "Card must read the published attribute to tell null from 0"
        )

    def test_combined_tooltip_mentions_combined_and_water_equivalent(self):
        source = CARD_JS.read_text()
        # The tooltip lives on a title= attribute.
        assert "title=" in source
        lowered = source.lower()
        assert "combined" in lowered
        assert "water equivalent" in lowered

    def test_has_yesterday_translation_keys(self):
        source = CARD_JS.read_text()
        for key in (
            "yesterday",
            "none",
            "noData",
            "yesterdayCombinedTooltip",
        ):
            assert f"{key}:" in source, f"missing translation key {key}"
