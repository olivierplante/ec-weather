"""Tests for today's probability-of-precipitation extraction (issue #9, Part A).

The card and a dedicated sensor surface "today's POP". The value is already
computed by merge_weong_into_daily as the combined day/night ``precip_prob``
on each daily period. ``extract_today_pop`` picks the value for today's date.
"""

from __future__ import annotations

from ec_weather.transforms import extract_today_pop

from .conftest import CARD_JS_PATH as CARD_JS


class TestExtractTodayPop:
    def test_returns_todays_combined_pop(self):
        """Given a merged daily list, return today's precip_prob."""
        merged = [
            {"date": "2026-06-08", "precip_prob": 70},
            {"date": "2026-06-09", "precip_prob": 20},
        ]
        assert extract_today_pop(merged, "2026-06-08") == 70

    def test_zero_pop_is_returned_not_treated_as_missing(self):
        """A real 0% POP must be returned as 0, not None."""
        merged = [{"date": "2026-06-08", "precip_prob": 0}]
        assert extract_today_pop(merged, "2026-06-08") == 0

    def test_missing_today_returns_none(self):
        """If today's date is not present, return None."""
        merged = [{"date": "2026-06-09", "precip_prob": 50}]
        assert extract_today_pop(merged, "2026-06-08") is None

    def test_none_pop_returns_none(self):
        """If today's period has a null precip_prob, return None."""
        merged = [{"date": "2026-06-08", "precip_prob": None}]
        assert extract_today_pop(merged, "2026-06-08") is None

    def test_empty_list_returns_none(self):
        """Empty merged list → None, no exception."""
        assert extract_today_pop([], "2026-06-08") is None

    def test_period_without_date_is_skipped(self):
        """A period missing its date key must not raise."""
        merged = [
            {"precip_prob": 99},
            {"date": "2026-06-08", "precip_prob": 30},
        ]
        assert extract_today_pop(merged, "2026-06-08") == 30


class TestTodayPopCard:
    """The current-conditions card surfaces today's POP from a dedicated sensor."""

    def test_card_renders_precip_panel(self):
        """Today's POP surfaces in the precipitation panel (redesign)."""
        source = CARD_JS.read_text()
        assert "ppanel" in source, "Card must render the precipitation panel"

    def test_shared_dailyPrecip_function_exists(self):
        """A single dailyPrecip() helper is the source of truth for POP+amounts."""
        source = CARD_JS.read_text()
        assert "function dailyPrecip(" in source, (
            "POP/amount logic must live in one shared dailyPrecip() function"
        )
        # Both the column and the current-conditions line must call it, not
        # reimplement the rounding/gating/amount logic.
        assert source.count("dailyPrecip(") >= 3, (
            "dailyPrecip() must be defined once and called by both call sites"
        )

    def test_pop_gating_and_amounts_in_shared_function(self):
        """The shared function gates on >=5% and exposes rain/snow amounts."""
        source = CARD_JS.read_text()
        start = source.find("function dailyPrecip(")
        section = source[start:start + 1000]
        assert "popRounded >= 5" in section, "POP gated on >=5% threshold"
        assert "rain_mm_day" in section and "snow_cm_day" in section
        assert "precip_accum_amount" in section, "EC accumulation preferred"

    def test_today_row_uses_daily_forecast_entry(self):
        """The panel's Today row reads today's daily forecast entry through
        the shared dailyPrecip() so it never diverges from the daily column."""
        source = CARD_JS.read_text()
        start = source.find("_renderCurrent() {")
        section = source[start:source.find("_renderHourly() {", start)]
        # Entity ids are resolved by role now (see LEGACY_ENTITY_IDS + the
        # ec_weather/entities command); the Today row reads 'daily_forecast'.
        assert "entityIdFor('daily_forecast')" in section
        assert "dailyPrecip(" in section
        # Amounts render through the shared precipAmtLabels() helper, which
        # emits compact no-space units ("3mm"/"5cm") via fmtAmtUnit.
        assert "precipAmtLabels(" in section
        # Amounts carry mdi icons so they read without labels: a filled
        # droplet on rain, a snowflake on snow. The chance % lives in the
        # panel header ("N% chance" / "None expected").
        assert "mdi:water" in section, "rain amount must carry a droplet icon"
        assert "mdi:snowflake" in section, "snow amount must carry a snowflake icon"
        assert "popRounded" in section, "chance % comes from the shared gate"
