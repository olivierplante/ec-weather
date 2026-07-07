"""Tests for the timesteps_state tri-state (loaded / unavailable / pending).

Background: EC removed the GDPS-WEonG layers from GeoMet, so daily-forecast
periods for days 4-6 return zero timesteps. An empty timestep list is
ambiguous — it looks identical whether the day was fetched-and-empty or has
simply not been fetched yet. These tests pin the disambiguation: a day that
completed its queries counts as "fetched" even when it produced zero results.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant

from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.transforms import merge_weong_into_daily

from .conftest import MOCK_CONFIG_DATA


# ---------------------------------------------------------------------------
# Helpers (copied minimal builders from test_daily_sensor.py)
# ---------------------------------------------------------------------------

def _daily_item(
    period: str,
    date: str,
    temp_high: float | None = 1,
    temp_low: float | None = -10,
    **overrides,
) -> dict:
    """Build a minimal daily forecast item."""
    base = {
        "period": period,
        "date": date,
        "temp_high": temp_high,
        "temp_low": temp_low,
        "icon_code": 16,
        "icon_code_night": 38,
        "condition_day": "Snow",
        "condition_night": "Cloudy periods",
        "text_summary_day": "Snow. High 1.",
        "text_summary_night": "Cloudy. Low minus 10.",
    }
    base.update(overrides)
    return base


def _weong_period(
    pop: int = 65,
    rain: float | None = 3.2,
    snow: float | None = None,
    timesteps: list | None = None,
) -> dict:
    """Build a minimal WEonG period item."""
    return {
        "pop": pop,
        "rain_mm": rain,
        "snow_cm": snow,
        "timesteps": timesteps or [],
    }


def _make_weong_coordinator(hass: HomeAssistant) -> ECWEonGCoordinator:
    """Create a WEonG coordinator with mock config."""
    return ECWEonGCoordinator(
        hass,
        geomet_bbox=MOCK_CONFIG_DATA["geomet_bbox"],
    )


def _make_periods(
    date_str: str, period_type: str, utc_start: datetime, utc_end: datetime,
) -> list[tuple[str, str, datetime, datetime]]:
    """Build a minimal periods list for projection tests."""
    return [(date_str, period_type, utc_start, utc_end)]


# ---------------------------------------------------------------------------
# merge_weong_into_daily — timesteps_state tri-state
# ---------------------------------------------------------------------------

class TestTimestepsState:
    def test_loaded_when_timesteps_present(self):
        """Non-empty timesteps → 'loaded' regardless of days_fetched."""
        daily = [_daily_item("Monday", "2026-03-23")]
        timestep = {
            "time": "2026-03-23T14:00:00Z",
            "temp": -3,
            "rain_mm": 1.0,
            "snow_cm": 0,
            "sky_state": None,
            "icon_code": 12,
            "condition": "Rain",
        }
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=50, timesteps=[timestep]),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(daily, weong_periods, days_fetched=[])

        assert result[0]["timesteps_state"] == "loaded"

    def test_unavailable_when_empty_and_day_fetched(self):
        """Empty timesteps + date in days_fetched → 'unavailable'.

        This is the GDPS-WEonG removal case: the day's queries completed but
        EC returned nothing, so there genuinely is no hourly detail.
        """
        daily = [_daily_item("Thursday", "2026-03-26")]
        weong_periods = {
            ("2026-03-26", "day"): _weong_period(pop=50),
            ("2026-03-26", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(
            daily, weong_periods, days_fetched=["2026-03-26"],
        )

        assert result[0]["timesteps_state"] == "unavailable"

    def test_pending_when_empty_and_day_not_fetched(self):
        """Empty timesteps + date NOT in days_fetched → 'pending'."""
        daily = [_daily_item("Thursday", "2026-03-26")]
        weong_periods = {
            ("2026-03-26", "day"): _weong_period(pop=50),
            ("2026-03-26", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(
            daily, weong_periods, days_fetched=["2026-03-25"],
        )

        assert result[0]["timesteps_state"] == "pending"

    def test_pending_when_days_fetched_none(self):
        """Empty timesteps + days_fetched=None → 'pending' (default)."""
        daily = [_daily_item("Thursday", "2026-03-26")]
        weong_periods = {
            ("2026-03-26", "day"): _weong_period(pop=50),
            ("2026-03-26", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(daily, weong_periods, days_fetched=None)

        assert result[0]["timesteps_state"] == "pending"

    def test_default_days_fetched_is_pending(self):
        """Omitting days_fetched entirely behaves like None → 'pending'."""
        daily = [_daily_item("Thursday", "2026-03-26")]
        weong_periods = {
            ("2026-03-26", "day"): _weong_period(pop=50),
            ("2026-03-26", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert result[0]["timesteps_state"] == "pending"


# ---------------------------------------------------------------------------
# icons_complete regression pin — unchanged by timesteps_state
# ---------------------------------------------------------------------------

class TestIconsCompleteUnchanged:
    def test_icons_complete_vacuously_true_for_zero_timesteps(self):
        """Zero timesteps → icons_complete stays vacuously True.

        The card's lazy-fetch guard depends on this — must not regress when
        timesteps_state marks the day 'unavailable'.
        """
        daily = [_daily_item("Thursday", "2026-03-26")]
        weong_periods = {
            ("2026-03-26", "day"): _weong_period(pop=50),
            ("2026-03-26", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(
            daily, weong_periods, days_fetched=["2026-03-26"],
        )

        assert result[0]["icons_complete"] is True
        assert result[0]["timesteps_state"] == "unavailable"


# ---------------------------------------------------------------------------
# Coordinator — days_fetched in projected output
# ---------------------------------------------------------------------------

class TestCompletedDaysProjection:
    def test_completed_days_starts_empty(self, hass: HomeAssistant):
        """A fresh coordinator has no completed days."""
        coord = _make_weong_coordinator(hass)
        assert coord._completed_days == set()

    def test_project_output_includes_empty_days_fetched(self, hass: HomeAssistant):
        """_project_output exposes days_fetched (empty when nothing fetched)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = coord._project_output(periods)

        assert output["days_fetched"] == []

    def test_project_output_reflects_completed_days(self, hass: HomeAssistant):
        """Adding completed dates changes the projected days_fetched (sorted)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        coord._completed_days.add("2026-03-24")
        coord._completed_days.add("2026-03-22")

        output = coord._project_output(periods)

        assert output["days_fetched"] == ["2026-03-22", "2026-03-24"]
