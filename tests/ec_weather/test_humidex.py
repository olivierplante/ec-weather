"""Tests for humidex parsing and local computation.

Covers two bugs:
  - Bug 1: daily forecast periods publish humidex as {"calculated": {"en": "32"}}
    (string value), which the old num()-only path could not read.
  - Bug 2: currentConditions often omits humidex entirely, so heat feels-like
    must be computed locally from temperature + dewpoint.
"""

from __future__ import annotations

import pytest

from ec_weather.parsing import (
    _parse_humidex,
    compute_humidex,
    feels_like,
)


# ---------------------------------------------------------------------------
# _parse_humidex — both EC shapes
# ---------------------------------------------------------------------------

class TestParseHumidex:
    def test_reads_calculated_string_shape(self):
        """Daily period shape {"calculated": {"en": "32"}} → 32.0."""
        period = {"humidex": {"calculated": {"en": "32"}}}
        assert _parse_humidex(period, "en") == 32.0

    def test_reads_calculated_french(self):
        """calculated shape honours the requested language."""
        period = {"humidex": {"calculated": {"en": "32", "fr": "33"}}}
        assert _parse_humidex(period, "fr") == 33.0

    def test_reads_value_measurement_shape(self):
        """Hourly-style shape {"value": {"en": 35}} still works."""
        period = {"humidex": {"value": {"en": 35}}}
        assert _parse_humidex(period, "en") == 35.0

    def test_absent_humidex_returns_none(self):
        assert _parse_humidex({}, "en") is None

    def test_non_dict_humidex_returns_none(self):
        assert _parse_humidex({"humidex": "32"}, "en") is None

    def test_empty_dict_returns_none(self):
        assert _parse_humidex({"humidex": {}}, "en") is None

    def test_malformed_calculated_returns_none(self):
        """Non-numeric calculated string → None."""
        period = {"humidex": {"calculated": {"en": "n/a"}}}
        assert _parse_humidex(period, "en") is None


# ---------------------------------------------------------------------------
# compute_humidex — MSC formula + EC display convention guards
# ---------------------------------------------------------------------------

class TestComputeHumidex:
    def test_reference_point(self):
        """30 C, dewpoint 15 C → ~34.0 by the MSC humidex formula."""
        assert compute_humidex(30.0, 15.0) == pytest.approx(34.0, abs=0.1)

    def test_temp_none_returns_none(self):
        assert compute_humidex(None, 15.0) is None

    def test_dewpoint_none_returns_none(self):
        assert compute_humidex(30.0, None) is None

    def test_temp_below_20_returns_none(self):
        assert compute_humidex(19.9, 15.0) is None

    def test_low_humidity_below_display_threshold_returns_none(self):
        """Dry heat where humidex < temp + 1 is not displayed by EC → None."""
        assert compute_humidex(25.0, 5.0) is None

    def test_hot_humid_returns_value(self):
        result = compute_humidex(26.0, 18.0)
        assert result is not None
        assert result > 26.0


# ---------------------------------------------------------------------------
# feels_like — unchanged behaviour when humidex is None
# ---------------------------------------------------------------------------

class TestFeelsLikeWithNoHumidex:
    def test_hot_no_humidex_returns_temp(self):
        """Hot, calm, no humidex → feels_like falls back to actual temp."""
        assert feels_like(26.0, 3.0, None) == 26.0

    def test_hot_with_humidex_returns_humidex(self):
        assert feels_like(26.0, 3.0, 32.0) == 32.0
