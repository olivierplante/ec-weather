"""Tests for the probability-of-precipitation DISPLAY rule (backend-owned).

Every user-facing POP is rounded UP to the next multiple of 5 and hidden when
the rounded value falls below ``POP_DISPLAY_MIN`` — so the card, the weather
entity, automations and voice assistants all read the same stepped number.

The rule is a PRESENTATION rule applied at the attribute-emission boundary.
All internal math (the expected-amount weighting in ``aggregate_expected_precip``,
the in-progress ``apply_remaining_only`` re-aggregation, and any store-level
aggregation) runs on the RAW store POPs BEFORE the display rule — these tests
pin that ordering so a low-POP hour keeps weighting its expected amount honestly
while the number a human reads is stepped.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from ec_weather.sensor import (
    ECDailyForecastSensor,
    ECHourlyForecastSensor,
    ECTodayPopSensor,
)
from ec_weather.transforms import (
    POP_DISPLAY_MIN,
    apply_display_pop,
    build_daily_view,
    display_pop,
)
from ec_weather.weather import ECWeather


# ---------------------------------------------------------------------------
# The atomic rule
# ---------------------------------------------------------------------------

class TestDisplayPopMatrix:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, None),
            (0, None),
            (1, None),
            (5, None),      # rounds to 5, below the 10 floor → hidden
            (6, 10),
            (8, 10),
            (10, 10),
            (11, 15),
            (23, 25),
            (25, 25),
            (56, 60),
            (100, 100),
        ],
    )
    def test_matrix(self, raw, expected):
        assert display_pop(raw) == expected

    def test_floor_constant_is_ten(self):
        assert POP_DISPLAY_MIN == 10

    def test_is_idempotent(self):
        """A value already stepped survives a second pass unchanged."""
        for raw in (None, 3, 6, 23, 55, 100):
            once = display_pop(raw)
            assert display_pop(once) == once


# ---------------------------------------------------------------------------
# apply_display_pop — the daily-view emission walker
# ---------------------------------------------------------------------------

class TestApplyDisplayPop:
    def test_steps_daily_pop_fields(self):
        view = [{"precip_prob": 23, "precip_prob_day": 8, "precip_prob_night": 3}]
        apply_display_pop(view)
        assert view[0]["precip_prob"] == 25
        assert view[0]["precip_prob_day"] == 10
        assert view[0]["precip_prob_night"] is None  # raw 3 → hidden

    def test_steps_displayed_timestep_pops(self):
        view = [{
            "precip_prob_day": 60,
            "timesteps_day": [
                {"time": "t1", "precipitation_probability": 8},
                {"time": "t2", "precipitation_probability": 3},
                {"time": "t3", "precipitation_probability": None},
            ],
            "timesteps_night": [
                {"time": "t4", "precipitation_probability": 56},
            ],
        }]
        apply_display_pop(view)
        pops_day = [ts["precipitation_probability"] for ts in view[0]["timesteps_day"]]
        assert pops_day == [10, None, None]
        assert view[0]["timesteps_night"][0]["precipitation_probability"] == 60

    def test_steps_outlook_detail_pops_and_sentence(self):
        view = [{
            "source": "outlook",
            "pop_day": 23,
            "pop_night": 4,
            "pop_day_display": 25,   # already stepped upstream — left alone
            "pop_night_display": None,
            "sentence": {"dominant_pop": 23, "amount_band": None},
        }]
        apply_display_pop(view)
        assert view[0]["pop_day"] == 25
        assert view[0]["pop_night"] is None
        # pop_*_display carries the >= 30 list gate and is stepped upstream.
        assert view[0]["pop_day_display"] == 25
        assert view[0]["sentence"]["dominant_pop"] == 25

    def test_leaves_non_pop_fields_untouched(self):
        view = [{"precip_prob": 60, "temp_high": 22, "rain_mm_day": 4.7}]
        apply_display_pop(view)
        assert view[0]["temp_high"] == 22
        assert view[0]["rain_mm_day"] == 4.7


# ---------------------------------------------------------------------------
# Ordering: internal math consumes RAW, only the emitted field is stepped
# ---------------------------------------------------------------------------

class TestRawMathPreservedBeforeDisplayRule:
    @freeze_time("2026-07-14T20:30:00Z")
    def test_expected_amount_uses_raw_pop_while_emitted_pop_is_stepped(self):
        """A straddling night re-aggregates its expected rain from the RAW POP.

        The remaining 21:00 hour carries a raw 23% POP over 10 mm of conditional
        rain, so the expected amount is 0.23 * 10 = 2.3 mm. Had the display rule
        (23 → 25) leaked into the weighting, the amount would be 2.5 mm. The
        emitted POP is then stepped to 25 by the display pass — the amount is not
        re-touched.
        """
        daily = [{
            "period": "Tuesday", "date": "2026-07-14",
            "temp_high": 24, "temp_low": 12,
            "icon_code": 1, "icon_code_night": 30,
        }]
        weong_periods = {
            ("2026-07-14", "night"): {
                "pop": 23, "rain_mm": None, "snow_cm": None,
                "timesteps": [
                    {"time": "2026-07-14T20:00:00Z",
                     "precipitation_probability": 80, "rain_mm": 5.0, "snow_cm": None},
                    {"time": "2026-07-14T21:00:00Z",
                     "precipitation_probability": 23, "rain_mm": 10.0, "snow_cm": None},
                ],
            },
        }

        view = build_daily_view(
            daily, weong_periods, [], "2026-07-14", model_precip_estimate=True,
        )
        row = view[0]
        # build_daily_view is a pure transform: the emitted POP is still RAW here.
        assert row["precip_prob_night"] == 23
        # Expected rain was weighted by the RAW 23%, not the stepped 25%.
        assert row["rain_mm_night"] == pytest.approx(2.3)

        apply_display_pop(view)
        # Only now — at the emission boundary — is the POP stepped for display.
        assert row["precip_prob_night"] == 25
        # The expected amount is untouched by the display pass.
        assert row["rain_mm_night"] == pytest.approx(2.3)


# ---------------------------------------------------------------------------
# Emission points — the actual entities step their user-facing POP
# ---------------------------------------------------------------------------

def _weather_data(daily, hourly):
    coord = MagicMock()
    coord.last_update_success = True
    coord.data = {"daily": daily, "hourly": hourly, "updated": "2026-07-14T18:00:00Z"}
    return coord


class TestHourlySensorSteps:
    @freeze_time("2026-07-14T12:00:00Z")
    def test_forecast_pop_is_stepped(self, hass: HomeAssistant):
        weather = _weather_data([], [])
        weong = MagicMock()
        weong.data = {"hourly": {
            "2026-07-14T18:00:00Z": {
                "rain_mm": 1.0, "snow_cm": None, "sky_state": 5, "temp": 20,
                "precipitation_probability": 8,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
            },
            "2026-07-14T19:00:00Z": {
                "rain_mm": 0.0, "snow_cm": None, "sky_state": 5, "temp": 19,
                "precipitation_probability": 3,
                "freezing_precip_mm": None, "ice_pellet_cm": None,
            },
        }}
        sensor = ECHourlyForecastSensor(weather, weong, "qc-68", "Test", "en")
        forecast = sensor.extra_state_attributes["forecast"]
        by_time = {item["time"]: item for item in forecast}
        assert by_time["2026-07-14T18:00:00Z"]["precipitation_probability"] == 10
        assert by_time["2026-07-14T19:00:00Z"]["precipitation_probability"] is None


class TestTodayPopSensorSteps:
    @freeze_time("2026-07-14T12:00:00Z")
    def test_state_is_stepped(self, hass: HomeAssistant):
        daily = [{
            "period": "Tuesday", "date": "2026-07-14",
            "temp_high": 24, "temp_low": 12,
            "icon_code": 1, "icon_code_night": 30,
        }]
        weather = _weather_data(daily, [])
        weong = MagicMock()
        weong.data = {
            "periods": {("2026-07-14", "day"): {
                "pop": 23, "rain_mm": None, "snow_cm": None, "timesteps": [],
            }},
            "updated": "2026-07-14T18:00:00Z",
        }
        sensor = ECTodayPopSensor(weather, weong, "qc-68", "Test", "en")
        assert sensor.native_value == 25


class TestDailySensorStepsAttributes:
    @freeze_time("2026-07-14T12:00:00Z")
    def test_forecast_pop_is_stepped(self, hass: HomeAssistant):
        daily = [{
            "period": "Tuesday", "date": "2026-07-14",
            "temp_high": 24, "temp_low": 12,
            "icon_code": 1, "icon_code_night": 30,
        }]
        weather = _weather_data(daily, [])
        weong = MagicMock()
        weong.data = {
            "periods": {
                ("2026-07-14", "day"): {
                    "pop": 23, "rain_mm": None, "snow_cm": None, "timesteps": [],
                },
                ("2026-07-14", "night"): {
                    "pop": 4, "rain_mm": None, "snow_cm": None, "timesteps": [],
                },
            },
            "updated": "2026-07-14T18:00:00Z",
            "days_fetched": ["2026-07-14"],
            "precip_windows": None, "outlook": None, "outlook_backfill": None,
        }
        sensor = ECDailyForecastSensor(weather, weong, "qc-68", "Test", "en")
        row = next(
            item for item in sensor.extra_state_attributes["forecast"]
            if item.get("date") == "2026-07-14"
        )
        assert row["precip_prob_day"] == 25
        assert row["precip_prob_night"] is None  # raw 4 → hidden
        assert row["precip_prob"] == 25


class TestWeatherEntitySteps:
    @freeze_time("2026-07-14T12:00:00Z")
    async def test_hourly_forecast_pop_is_stepped(self, hass: HomeAssistant):
        hourly = [
            {"time": "2026-07-14T18:00:00Z", "temp": 20, "icon_code": 1,
             "precipitation_probability": 8, "wind_speed": 10, "wind_direction": "N"},
            {"time": "2026-07-14T19:00:00Z", "temp": 19, "icon_code": 1,
             "precipitation_probability": 3, "wind_speed": 10, "wind_direction": "N"},
        ]
        weather = _weather_data([], hourly)
        weong = MagicMock()
        weong.data = None
        entity = ECWeather(weather, weong, "qc-68", "Test", "en")
        forecast = await entity.async_forecast_hourly()
        assert forecast[0]["precipitation_probability"] == 10
        assert forecast[1]["precipitation_probability"] is None

    @freeze_time("2026-07-14T12:00:00Z")
    async def test_daily_forecast_pop_is_stepped(self, hass: HomeAssistant):
        daily = [{
            "period": "2026-07-14", "date": "2026-07-14",
            "temp_high": 24, "temp_low": 12,
            "icon_code": 1, "icon_code_night": 30,
        }]
        weather = _weather_data(daily, [])
        weong = MagicMock()
        weong.data = {"periods": {("2026-07-14", "day"): {
            "pop": 23, "rain_mm": None, "snow_cm": None, "timesteps": [],
        }}}
        entity = ECWeather(weather, weong, "qc-68", "Test", "en")
        forecast = await entity.async_forecast_daily()
        assert forecast[0]["precipitation_probability"] == 25
