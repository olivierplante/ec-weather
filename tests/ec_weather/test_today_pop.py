"""Tests for today's probability-of-precipitation extraction (issue #9, Part A).

The card and a dedicated sensor surface "today's POP". The value is already
computed by merge_weong_into_daily as the combined day/night ``precip_prob``
on each daily period. ``extract_today_pop`` picks the value for today's date.
"""

from __future__ import annotations

from ec_weather.transforms import extract_today_pop


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
