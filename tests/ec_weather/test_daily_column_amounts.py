"""Tests for daily column precipitation amount source.

Daily columns prefer EC precip_accum (meteorologist-interpreted, days 0-2).
For days 3+ where EC has no accumulation estimate, WEonG model amounts
(rain_mm_day, snow_cm_day) are used as a fallback.

This ensures amounts are always visible when precipitation is forecast,
and values are stable (WEonG amounts are fetched in the background for
all wet timesteps, not lazily on popup open).
"""

from __future__ import annotations

from .conftest import CARD_JS_PATH as CARD_JS


class TestDailyColumnAmountSource:
    """Verify daily columns use EC precip_accum with WEonG fallback."""

    def test_prefers_ec_precip_accum(self):
        """Daily column must check EC precip_accum first."""
        source = CARD_JS.read_text()
        assert "hasEcAccum" in source, (
            "Daily column must check hasEcAccum before falling back to WEonG"
        )

    def test_falls_back_to_weong_when_no_ec_accum(self):
        """When EC has no accum, daily column uses WEonG rain_mm_day/snow_cm_day."""
        source = CARD_JS.read_text()
        # The else branch must reference WEonG amounts
        accum_section_start = source.find("hasEcAccum")
        accum_section_end = source.find("pColor", accum_section_start)
        accum_section = source[accum_section_start:accum_section_end]
        assert "rain_mm_day" in accum_section, (
            "WEonG rain_mm_day must be used as fallback when EC has no accum"
        )
        assert "snow_cm_day" in accum_section, (
            "WEonG snow_cm_day must be used as fallback when EC has no accum"
        )

    def test_popup_still_has_weong_amounts(self):
        """Popup timeline should still show WEonG per-timestep amounts."""
        source = CARD_JS.read_text()
        assert "rain_mm_day" in source
        assert "rain_mm_night" in source
