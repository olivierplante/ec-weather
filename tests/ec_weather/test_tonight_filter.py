"""Tests for filtering stale 'Tonight' period from daily forecast.

EC keeps the 'Tonight' night-only period in the forecast until the next
morning update. Between 6 AM and 6 PM local, it should be dropped from
the daily forecast since the night has passed. After 6 PM, EC issues a
fresh 'Tonight' for the upcoming night, so it should be kept.
"""

from __future__ import annotations


def _night_only_period(date: str = "2026-03-25") -> dict:
    """Build a night-only period (temp_high=None, like 'Tonight')."""
    return {
        "period": "Tonight",
        "date": date,
        "temp_high": None,
        "temp_low": -5,
        "icon_code": None,
        "icon_code_night": 33,
        "timesteps_day": [],
        "timesteps_night": [],
    }


def _full_day_period(period: str = "Wednesday", date: str = "2026-03-26") -> dict:
    """Build a full day+night period."""
    return {
        "period": period,
        "date": date,
        "temp_high": 2,
        "temp_low": -8,
        "icon_code": 1,
        "icon_code_night": 33,
        "timesteps_day": [],
        "timesteps_night": [],
    }


def _apply_tonight_filter(merged: list[dict], hour: int) -> list[dict]:
    """Simulate the Tonight filter logic from ECDailyForecastSensor."""
    if merged and merged[0].get("temp_high") is None and 6 <= hour < 18:
        return merged[1:]
    return merged


class TestTonightFilter:
    """Verify Tonight period is dropped after 6 AM."""

    def test_tonight_dropped_after_6am(self) -> None:
        """Night-only first period is removed when local hour >= 6."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=8)
        assert len(result) == 1
        assert result[0]["period"] == "Wednesday"

    def test_tonight_kept_before_6am(self) -> None:
        """Night-only first period is kept when local hour < 6."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=3)
        assert len(result) == 2
        assert result[0]["period"] == "Tonight"

    def test_tonight_dropped_at_exactly_6am(self) -> None:
        """Night-only period is removed at exactly 6 AM."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=6)
        assert len(result) == 1

    def test_full_day_first_not_dropped(self) -> None:
        """A full day+night period (temp_high set) is never dropped."""
        merged = [_full_day_period(), _full_day_period("Thursday", "2026-03-27")]
        result = _apply_tonight_filter(merged, hour=10)
        assert len(result) == 2

    def test_empty_forecast_no_crash(self) -> None:
        """No crash when forecast is empty."""
        result = _apply_tonight_filter([], hour=10)
        assert result == []

    def test_single_tonight_period(self) -> None:
        """Single night-only period results in empty list during daytime."""
        merged = [_night_only_period()]
        result = _apply_tonight_filter(merged, hour=10)
        assert result == []

    def test_tonight_kept_at_6pm(self) -> None:
        """Night-only period is kept at 6 PM — fresh Tonight for upcoming night."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=18)
        assert len(result) == 2
        assert result[0]["period"] == "Tonight"

    def test_tonight_kept_at_10pm(self) -> None:
        """Night-only period is kept at 10 PM — Tonight is the active forecast."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=22)
        assert len(result) == 2
        assert result[0]["period"] == "Tonight"

    def test_tonight_dropped_at_5pm(self) -> None:
        """Night-only period is still dropped at 5 PM (before evening cutoff)."""
        merged = [_night_only_period(), _full_day_period()]
        result = _apply_tonight_filter(merged, hour=17)
        assert len(result) == 1
        assert result[0]["period"] == "Wednesday"
