"""Tests for EC hourly forecast sensor — pure function tests."""

from __future__ import annotations

from freezegun import freeze_time

from ec_weather.transforms import (
    apply_icon_fallback,
    build_unified_hourly,
    derive_icon,
    filter_past_hours,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ec_hourly_item(dt: str, **overrides) -> dict:
    """Build a minimal EC hourly forecast item."""
    base = {
        "time": dt,
        "temp": -5,
        "feels_like": -10,
        "condition": "Cloudy",
        "icon_code": 3,
        "precipitation_probability": 30,
        "wind_speed": 20,
        "wind_gust": None,
        "wind_direction": "NW",
    }
    base.update(overrides)
    return base


def _weong_hourly_item(
    rain: float | None = None,
    snow: float | None = None,
    sky_state: int | None = 9,
    **overrides,
) -> dict:
    """Build a minimal WEonG hourly item."""
    base = {
        "rain_mm": rain,
        "snow_cm": snow,
        "sky_state": sky_state,
        "temp": -5,
        "precipitation_probability": 30,
        "freezing_precip_mm": None,
        "ice_pellet_cm": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _build_unified_hourly
# ---------------------------------------------------------------------------

class TestBuildUnifiedHourlyECOnly:
    def test_ec_only_no_weong(self):
        """Given EC hourly items and empty WEonG → rain/snow fields are None."""
        ec_hourly = [
            _ec_hourly_item("2026-03-23T14:00:00Z"),
            _ec_hourly_item("2026-03-23T15:00:00Z"),
        ]

        result = build_unified_hourly(ec_hourly, {})

        assert len(result) == 2
        for item in result:
            assert item["rain_mm"] is None
            assert item["snow_cm"] is None
            # Original EC fields preserved
            assert item["temp"] == -5
            assert item["icon_code"] == 3
            assert item["condition"] == "Cloudy"


class TestBuildUnifiedHourlyMerged:
    def test_merged_ec_plus_weong(self):
        """Given matching WEonG data → rain/snow enriched on EC items."""
        ec_hourly = [
            _ec_hourly_item("2026-03-23T14:00:00Z"),
            _ec_hourly_item("2026-03-23T15:00:00Z"),
        ]
        weong_hourly = {
            "2026-03-23T14:00:00Z": _weong_hourly_item(rain=1.5, snow=0.3),
            "2026-03-23T15:00:00Z": _weong_hourly_item(rain=None, snow=2.0),
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 2
        assert result[0]["rain_mm"] == 1.5
        assert result[0]["snow_cm"] == 0.3
        assert result[1]["rain_mm"] is None
        assert result[1]["snow_cm"] == 2.0
        # EC fields still preserved
        assert result[0]["temp"] == -5
        assert result[0]["icon_code"] == 3

    def test_weong_extends_to_48h(self):
        """Given WEonG entries beyond EC range → appended with derived fields."""
        ec_hourly = [
            _ec_hourly_item("2026-03-23T14:00:00Z"),
        ]
        weong_hourly = {
            "2026-03-23T14:00:00Z": _weong_hourly_item(rain=1.0),
            "2026-03-24T14:00:00Z": _weong_hourly_item(
                rain=2.5, sky_state=5, temp=-3, precipitation_probability=60,
            ),
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 2
        # First item is the EC item enriched
        assert result[0]["time"] == "2026-03-23T14:00:00Z"
        assert result[0]["rain_mm"] == 1.0
        # Second item is WEonG-only (beyond EC)
        extended = result[1]
        assert extended["time"] == "2026-03-24T14:00:00Z"
        assert extended["temp"] == -3
        assert extended["rain_mm"] == 2.5
        assert extended["precipitation_probability"] == 60
        # Wind fields are None for WEonG-only items
        assert extended["wind_speed"] is None
        assert extended["feels_like"] is None

    def test_icon_derived_when_ec_missing(self):
        """Given EC item with icon=None + WEonG sky_state → icon derived."""
        ec_hourly = [
            _ec_hourly_item(
                "2026-03-23T14:00:00Z", icon_code=None, condition=None,
            ),
        ]
        weong_hourly = {
            "2026-03-23T14:00:00Z": _weong_hourly_item(sky_state=3),
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 1
        # sky_state=3 at hour 14 (daytime) → icon_code=1, "Mainly sunny"
        assert result[0]["icon_code"] == 1
        assert result[0]["condition"] == "Mainly sunny"


# ---------------------------------------------------------------------------
# _filter_past_hours
# ---------------------------------------------------------------------------

class TestFilterPastHours:
    @freeze_time("2026-03-23T15:30:00Z")
    def test_past_hours_filtered(self):
        """Given frozen time at 15:30 → items before 15:00 removed."""
        forecast = [
            {"time": "2026-03-23T13:00:00Z", "temp": -5},
            {"time": "2026-03-23T14:00:00Z", "temp": -4},
            {"time": "2026-03-23T15:00:00Z", "temp": -3},
            {"time": "2026-03-23T16:00:00Z", "temp": -2},
            {"time": "2026-03-23T17:00:00Z", "temp": -1},
        ]

        result = filter_past_hours(forecast)

        assert len(result) == 3
        assert result[0]["time"] == "2026-03-23T15:00:00Z"
        assert result[1]["time"] == "2026-03-23T16:00:00Z"
        assert result[2]["time"] == "2026-03-23T17:00:00Z"


# ---------------------------------------------------------------------------
# _apply_icon_fallback
# ---------------------------------------------------------------------------

class TestApplyIconFallback:
    def test_icon_fallback_applied(self):
        """Given entry without icon_code + sky_state → icon set from sky_state."""
        entry = {
            "icon_code": None,
            "condition": None,
            "sky_state": 2,
            "rain_mm": 0,
            "snow_cm": 0,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
            "temp": -5,
        }

        apply_icon_fallback(entry, "2026-03-23T14:00:00Z")

        # sky_state=2 at hour 14 (daytime) → icon_code=0, "Sunny"
        assert entry["icon_code"] == 0
        assert entry["condition"] == "Sunny"

    def test_icon_fallback_skipped_when_present(self):
        """Given entry with existing icon_code → not overwritten."""
        entry = {"icon_code": 3, "condition": "Mostly cloudy"}

        apply_icon_fallback(entry, "2026-03-23T14:00:00Z")

        assert entry["icon_code"] == 3
        assert entry["condition"] == "Mostly cloudy"

    def test_icon_fallback_nighttime(self):
        """Given nighttime hour + sky_state → night icon codes used."""
        entry = {
            "icon_code": None,
            "condition": None,
            "sky_state": 1,
            "rain_mm": 0,
            "snow_cm": 0,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
            "temp": -5,
        }

        apply_icon_fallback(entry, "2026-03-23T22:00:00Z")

        # sky_state=1 at hour 22 (nighttime) → icon_code=30, "Clear"
        assert entry["icon_code"] == 30
        assert entry["condition"] == "Clear"

    def test_icon_fallback_rain(self):
        """Given rain > 0 and no icon → rain icon derived."""
        entry = {
            "icon_code": None,
            "condition": None,
            "rain_mm": 2.0,
            "snow_cm": 0,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
            "temp": 5,
        }

        apply_icon_fallback(entry, "2026-03-23T14:00:00Z")

        assert entry["icon_code"] == 12
        assert entry["condition"] == "Rain"
