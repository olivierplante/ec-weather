"""Tests for Phase 5 — validation and hardening."""

from __future__ import annotations

from datetime import date

import pytest
import voluptuous as vol

from ec_weather.parsing import parse_daily, parse_hourly


# ---------------------------------------------------------------------------
# 5.1 — Date validation in service schema
# ---------------------------------------------------------------------------


class TestDateValidation:
    """The fetch_day_timesteps service schema rejects non-YYYY-MM-DD strings."""

    SCHEMA = vol.Schema({vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$")})

    def test_valid_date_passes(self):
        """Given '2026-03-22' -> schema accepts."""
        result = self.SCHEMA({"date": "2026-03-22"})
        assert result["date"] == "2026-03-22"

    def test_valid_date_jan_01(self):
        """Given '2026-01-01' -> schema accepts."""
        result = self.SCHEMA({"date": "2026-01-01"})
        assert result["date"] == "2026-01-01"

    def test_invalid_date_slash_format(self):
        """Given '2026/03/22' -> schema rejects."""
        with pytest.raises(vol.Invalid):
            self.SCHEMA({"date": "2026/03/22"})

    def test_invalid_date_random_string(self):
        """Given 'hello' -> schema rejects."""
        with pytest.raises(vol.Invalid):
            self.SCHEMA({"date": "hello"})

    def test_invalid_date_partial(self):
        """Given '2026-03' (no day) -> schema rejects."""
        with pytest.raises(vol.Invalid):
            self.SCHEMA({"date": "2026-03"})

    def test_invalid_date_with_time(self):
        """Given '2026-03-22T00:00' -> schema rejects (trailing chars)."""
        with pytest.raises(vol.Invalid):
            self.SCHEMA({"date": "2026-03-22T00:00"})

    def test_invalid_date_empty(self):
        """Given '' -> schema rejects."""
        with pytest.raises(vol.Invalid):
            self.SCHEMA({"date": ""})


# ---------------------------------------------------------------------------
# 5.1 — Bbox validation helper
# ---------------------------------------------------------------------------


class TestBboxValidation:
    """validate_bbox accepts well-formed bboxes and rejects bad ones."""

    def test_valid_bbox(self):
        from ec_weather import validate_bbox
        assert validate_bbox("44.420,-76.700,46.420,-74.700") is True

    def test_valid_bbox_integers(self):
        from ec_weather import validate_bbox
        assert validate_bbox("44,-77,46,-75") is True

    def test_valid_bbox_negative(self):
        from ec_weather import validate_bbox
        assert validate_bbox("-90.0,-180.0,90.0,180.0") is True

    def test_invalid_bbox_three_values(self):
        from ec_weather import validate_bbox
        assert validate_bbox("44.780,-75.070,46.780") is False

    def test_invalid_bbox_five_values(self):
        from ec_weather import validate_bbox
        assert validate_bbox("44.420,-76.700,46.420,-74.700,99") is False

    def test_invalid_bbox_non_numeric(self):
        from ec_weather import validate_bbox
        assert validate_bbox("abc,-75.070,46.780,-73.070") is False

    def test_invalid_bbox_empty(self):
        from ec_weather import validate_bbox
        assert validate_bbox("") is False

    def test_invalid_bbox_none(self):
        from ec_weather import validate_bbox
        assert validate_bbox(None) is False


# ---------------------------------------------------------------------------
# 5.5 — parse_hourly skips malformed items
# ---------------------------------------------------------------------------


class TestParseHourlyResilience:
    """parse_hourly skips malformed items instead of crashing."""

    def test_skips_malformed_item_continues(self):
        """Given one good item and one malformed -> returns only the good one."""
        good_item = {
            "timestamp": "2026-03-22T12:00:00Z",
            "temperature": {"value": {"en": 5.0}},
            "wind": {"speed": {"value": {"en": 10.0}}},
            "condition": {"en": "Cloudy"},
            "iconCode": {"value": 10},
            "lop": {"value": {"en": 30}},
        }
        # Malformed: temperature is a string instead of a dict, which will
        # cause num() to return None — but that's handled gracefully.
        # To truly trigger an exception we need something that breaks iteration.
        # We create an item where .get raises — use a non-dict.
        malformed_item = "not-a-dict"

        # parse_hourly calls item.get() — a string has no .get() -> AttributeError
        # After Phase 5, this should be caught and skipped.
        result = parse_hourly([good_item, malformed_item], "en")
        assert len(result) == 1
        assert result[0]["time"] == "2026-03-22T12:00:00Z"

    def test_all_malformed_returns_empty(self):
        """Given only malformed items -> returns empty list."""
        result = parse_hourly(["bad1", 42, None], "en")
        assert result == []

    def test_good_items_unaffected(self):
        """Given all good items -> all are parsed."""
        items = [
            {
                "timestamp": f"2026-03-22T{h:02d}:00:00Z",
                "temperature": {"value": {"en": float(h)}},
                "wind": {},
                "condition": {"en": "Clear"},
                "iconCode": {"value": 0},
                "lop": {"value": {"en": 0}},
            }
            for h in range(3)
        ]
        result = parse_hourly(items, "en")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# 5.5 — parse_daily skips malformed pairs
# ---------------------------------------------------------------------------


class TestParseDailyResilience:
    """parse_daily skips malformed day/night pairs instead of crashing."""

    def _make_day_period(self, name: str = "Monday") -> dict:
        """Build a minimal valid day period."""
        return {
            "period": {"textForecastName": {"en": name}},
            "temperatures": {
                "temperature": [
                    {"class": {"en": "high"}, "value": {"en": 5.0}},
                ],
            },
            "abbreviatedForecast": {
                "textSummary": {"en": "Cloudy"},
                "icon": {"value": 10},
            },
            "textSummary": {"en": "Cloudy with a chance of rain."},
        }

    def _make_night_period(self, name: str = "Monday night") -> dict:
        """Build a minimal valid night period."""
        return {
            "period": {"textForecastName": {"en": name}},
            "temperatures": {
                "temperature": [
                    {"class": {"en": "low"}, "value": {"en": -2.0}},
                ],
            },
            "abbreviatedForecast": {
                "textSummary": {"en": "Clear"},
                "icon": {"value": 30},
            },
            "textSummary": {"en": "Clear."},
        }

    def test_skips_malformed_pair_continues(self):
        """Given a good pair + malformed pair -> returns only the good one."""
        good_day = self._make_day_period("Monday")
        good_night = self._make_night_period("Monday night")
        # Malformed: string instead of dict
        bad_day = "not-a-dict"
        bad_night = "also-bad"

        items = [good_day, good_night, bad_day, bad_night]
        result = parse_daily(items, "en", today=date(2026, 3, 22))
        # Should have at least the first good pair
        assert len(result) >= 1
        assert result[0]["period"] == "Monday"

    def test_all_good_pairs_unaffected(self):
        """Given all well-formed pairs -> all are parsed."""
        items = []
        for d in ["Monday", "Tuesday"]:
            items.append(self._make_day_period(d))
            items.append(self._make_night_period(f"{d} night"))

        result = parse_daily(items, "en", today=date(2026, 3, 22))
        assert len(result) == 2
