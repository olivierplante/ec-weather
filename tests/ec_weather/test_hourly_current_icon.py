"""Tests for hourly forecast icon handling.

Phase D removed the current-hour icon fallback hack. The hourly sensor
now returns WEonG-derived icons as-is — icon derivation happens in
build_unified_hourly via apply_icon_fallback, not in the sensor.

Tests verify:
1. WEonG items with sky_state get derived icons via build_unified_hourly
2. WEonG items without sky_state or precip have icon_code=None (honest)
3. EC hourly items always have their own icon (no fallback needed)
"""

from __future__ import annotations

from ec_weather.transforms import build_unified_hourly


class TestHourlyIconDerivation:
    """Verify icon derivation in the unified hourly pipeline."""

    def test_weong_item_with_sky_state_gets_icon(self) -> None:
        """WEonG-only item with sky_state gets a derived icon."""
        ec_hourly = []
        weong_hourly = {
            "2026-03-25T15:00:00Z": {
                "temp": -3.0, "sky_state": 2.0,
                "rain_mm": None, "snow_cm": None,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
                "precipitation_probability": 0,
            },
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 1
        # sky_state=2 at hour 15 (daytime) → icon_code=0 (Sunny)
        assert result[0]["icon_code"] == 0
        assert result[0]["condition"] == "Sunny"

    def test_weong_item_without_sky_state_has_null_icon(self) -> None:
        """WEonG-only item without sky_state or precip has icon_code=None."""
        ec_hourly = []
        weong_hourly = {
            "2026-03-25T15:00:00Z": {
                "temp": -3.0, "sky_state": None,
                "rain_mm": None, "snow_cm": None,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
                "precipitation_probability": 0,
            },
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 1
        assert result[0]["icon_code"] is None

    def test_ec_item_keeps_own_icon(self) -> None:
        """EC hourly item always keeps its own icon, not overwritten."""
        ec_hourly = [
            {"time": "2026-03-25T15:00:00Z", "temp": -3.0, "icon_code": 3,
             "condition": "Cloudy", "feels_like": -7.0,
             "wind_speed": 15, "wind_gust": None, "wind_direction": "NW",
             "precipitation_probability": 10},
        ]
        weong_hourly = {
            "2026-03-25T15:00:00Z": {
                "temp": -4.0, "sky_state": 1.0,  # would derive sunny, but EC icon wins
                "rain_mm": None, "snow_cm": None,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
                "precipitation_probability": 10,
            },
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 1
        assert result[0]["icon_code"] == 3  # EC icon preserved
        assert result[0]["condition"] == "Cloudy"

    def test_weong_item_with_precip_gets_precip_icon(self) -> None:
        """WEonG-only item with rain gets a rain icon (no sky_state needed)."""
        ec_hourly = []
        weong_hourly = {
            "2026-03-25T15:00:00Z": {
                "temp": 2.0, "sky_state": None,
                "rain_mm": 1.5, "snow_cm": None,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
                "precipitation_probability": 80,
            },
        }

        result = build_unified_hourly(ec_hourly, weong_hourly)

        assert len(result) == 1
        assert result[0]["icon_code"] == 12  # Rain icon
        assert result[0]["condition"] == "Rain"
