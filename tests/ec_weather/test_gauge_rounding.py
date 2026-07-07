"""Tests for gauge label rounding (iOS widget vs card discrepancy).

The card rounds with JS Math.round (half UP: 24.5 → 25); Python's built-in
round() uses banker's rounding (half to EVEN: 24.5 → 24), so the iOS widget
showed 24 while the dashboard showed 25 for the same 24.5° reading.
_format_temp_label must match JS Math.round exactly — including negative
halves, where JS rounds toward +infinity (-24.5 → -24).
"""

from __future__ import annotations

from ec_weather.sensor import _format_temp_label


class TestFormatTempLabel:
    def test_positive_half_rounds_up_like_the_card(self):
        assert _format_temp_label(24.5) == "25"

    def test_negative_half_matches_js_math_round(self):
        assert _format_temp_label(-24.5) == "-24"

    def test_below_half_rounds_down(self):
        assert _format_temp_label(23.4) == "23"

    def test_above_half_rounds_up(self):
        assert _format_temp_label(23.6) == "24"

    def test_whole_number_unchanged(self):
        assert _format_temp_label(-14.0) == "-14"

    def test_none_stays_none(self):
        assert _format_temp_label(None) is None
