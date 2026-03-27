"""Tests for EC daily forecast sensor — pure function tests."""

from __future__ import annotations

from freezegun import freeze_time

from ec_weather.transforms import (
    apply_icon_fallback,
    filter_past_hours,
    merge_weong_into_daily,
)


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# _merge_weong_into_daily — no WEonG data
# ---------------------------------------------------------------------------

class TestMergeWeongIntoDailyNoWeong:
    def test_ec_only_no_weong(self):
        """Given empty weong_periods → raw daily items returned with null precip fields."""
        daily = [
            _daily_item("Monday", "2026-03-23"),
            _daily_item("Tuesday", "2026-03-24"),
        ]

        result = merge_weong_into_daily(daily, {})

        assert len(result) == 2
        for item in result:
            assert item["precip_prob_day"] is None
            assert item["precip_prob_night"] is None
            assert item["precip_prob"] is None
            assert item["rain_mm_day"] is None
            assert item["snow_cm_day"] is None


# ---------------------------------------------------------------------------
# _merge_weong_into_daily — WEonG enrichment
# ---------------------------------------------------------------------------

class TestMergeWeongIntoDailyEnriched:
    def test_weong_enriches_precip(self):
        """Given WEonG data for day+night → POP and amounts added."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(
                pop=65, rain=3.2, snow=None,
            ),
            ("2026-03-23", "night"): _weong_period(
                pop=40, rain=1.0, snow=0.5,
            ),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert len(result) == 1
        item = result[0]
        assert item["precip_prob_day"] == 65
        assert item["rain_mm_day"] == 3.2
        assert item["snow_cm_day"] is None
        assert item["precip_prob_night"] == 40
        assert item["rain_mm_night"] == 1.0
        assert item["snow_cm_night"] == 0.5

    def test_combined_precip_prob_is_max(self):
        """Given day POP=30, night POP=60 → combined = 60 (max)."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=30),
            ("2026-03-23", "night"): _weong_period(pop=60),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert result[0]["precip_prob"] == 60


# ---------------------------------------------------------------------------
# _merge_weong_into_daily — timestep enrichment
# ---------------------------------------------------------------------------

class TestMergeWeongTimesteps:
    def test_timesteps_enriched_with_ec_hourly(self):
        """Given timesteps + EC hourly data → timesteps get EC fields merged."""
        daily = [_daily_item("Monday", "2026-03-23")]
        timestep = {
            "time": "2026-03-23T14:00:00Z",
            "temp": -4,
            "rain_mm": 0,
            "snow_cm": 0,
            "sky_state": 5,
            "precipitation_probability": None,
            "icon_code": None,
            "condition": None,
        }
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(
                pop=50, timesteps=[timestep],
            ),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }
        ec_hourly = [
            {
                "time": "2026-03-23T14:00:00Z",
                "temp": -5.0,
                "feels_like": -10.0,
                "icon_code": 3,
                "condition": "Mostly cloudy",
                "wind_speed": 20,
                "wind_direction": "NW",
                "wind_gust": 35,
            },
        ]

        result = merge_weong_into_daily(
            daily, weong_periods, hourly_forecast=ec_hourly,
        )

        ts_day = result[0]["timesteps_day"]
        assert len(ts_day) == 1
        enriched_ts = ts_day[0]
        # EC hourly temp preferred over WEonG temp
        assert enriched_ts["temp"] == -5.0
        assert enriched_ts["feels_like"] == -10.0
        assert enriched_ts["icon_code"] == 3
        assert enriched_ts["condition"] == "Mostly cloudy"
        assert enriched_ts["wind_speed"] == 20
        assert enriched_ts["wind_direction"] == "NW"

    def test_timestep_icon_fallback(self):
        """Given timestep without EC data → icon derived from sky_state."""
        daily = [_daily_item("Monday", "2026-03-23")]
        timestep = {
            "time": "2026-03-23T14:00:00Z",
            "temp": -3,
            "rain_mm": 0,
            "snow_cm": 0,
            "sky_state": 2,
            "icon_code": None,
            "condition": None,
            "freezing_precip_mm": 0,
            "ice_pellet_cm": 0,
        }
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(
                pop=10, timesteps=[timestep],
            ),
            ("2026-03-23", "night"): _weong_period(pop=5),
        }

        # No EC hourly data → icon must be derived
        result = merge_weong_into_daily(daily, weong_periods, hourly_forecast=[])

        ts_day = result[0]["timesteps_day"]
        assert len(ts_day) == 1
        enriched_ts = ts_day[0]
        # sky_state=2 at hour 14 (daytime) → icon_code=0, "Sunny"
        assert enriched_ts["icon_code"] == 0
        assert enriched_ts["condition"] == "Sunny"


# ---------------------------------------------------------------------------
# _merge_weong_into_daily — edge cases
# ---------------------------------------------------------------------------

class TestMergeWeongEdgeCases:
    def test_merge_handles_missing_dates(self):
        """Given WEonG data for dates not in daily → no crash, daily unchanged."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-25", "day"): _weong_period(pop=80),
            ("2026-03-25", "night"): _weong_period(pop=70),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert len(result) == 1
        # No WEonG match for 2026-03-23 → all precip fields None
        assert result[0]["precip_prob"] is None
        assert result[0]["precip_prob_day"] is None
        assert result[0]["precip_prob_night"] is None

    def test_night_only_period(self):
        """Given night-only period (temp_high=None) → day fields are None."""
        daily = [
            _daily_item(
                "Tonight", "2026-03-22",
                temp_high=None, temp_low=-8,
                icon_code=None, icon_code_night=33,
            ),
        ]
        weong_periods = {
            ("2026-03-22", "night"): _weong_period(pop=25, rain=0.5),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert len(result) == 1
        item = result[0]
        # Day fields should be None (night-only period)
        assert item["precip_prob_day"] is None
        assert item["rain_mm_day"] is None
        # Night fields populated
        assert item["precip_prob_night"] == 25
        assert item["rain_mm_night"] == 0.5
        assert item["precip_prob"] == 25


# ---------------------------------------------------------------------------
# icons_complete
# ---------------------------------------------------------------------------

class TestIconsComplete:
    def test_all_icons_resolved(self):
        """Given all timesteps have icon_code → icons_complete is True."""
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

        result = merge_weong_into_daily(daily, weong_periods)

        assert result[0]["icons_complete"] is True

    def test_some_icons_missing(self):
        """Given a timestep with icon_code=None → icons_complete is False."""
        daily = [_daily_item("Monday", "2026-03-23")]
        ts_with_icon = {
            "time": "2026-03-23T14:00:00Z",
            "temp": -3,
            "rain_mm": 1.0,
            "snow_cm": 0,
            "sky_state": None,
            "icon_code": 12,
            "condition": "Rain",
        }
        ts_without_icon = {
            "time": "2026-03-23T15:00:00Z",
            "temp": -2,
            "rain_mm": 0,
            "snow_cm": 0,
            "sky_state": None,
            "icon_code": None,
            "condition": None,
        }
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(
                pop=50, timesteps=[ts_with_icon, ts_without_icon],
            ),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert result[0]["icons_complete"] is False

    def test_no_timesteps(self):
        """Given no timesteps → icons_complete is True (nothing to resolve)."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=50),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }

        result = merge_weong_into_daily(daily, weong_periods)

        assert result[0]["icons_complete"] is True


# ---------------------------------------------------------------------------
# merge_weong_into_daily — updated timestamp (oldest of EC / WEonG)
# ---------------------------------------------------------------------------

class TestMergeWeongUpdatedTimestamp:
    """Each period gets an 'updated' field = min(ec_updated, weong_updated)."""

    def test_updated_uses_older_timestamp(self) -> None:
        """When both timestamps given, updated = the older one."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=30),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }
        result = merge_weong_into_daily(
            daily, weong_periods,
            ec_updated="2026-03-23T14:00:00+00:00",
            weong_updated="2026-03-23T12:00:00+00:00",
        )
        assert result[0]["updated"] == "2026-03-23T12:00:00+00:00"

    def test_updated_uses_ec_when_older(self) -> None:
        """When EC is older, updated = EC timestamp."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=30),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }
        result = merge_weong_into_daily(
            daily, weong_periods,
            ec_updated="2026-03-23T10:00:00+00:00",
            weong_updated="2026-03-23T12:00:00+00:00",
        )
        assert result[0]["updated"] == "2026-03-23T10:00:00+00:00"

    def test_updated_none_when_no_timestamps(self) -> None:
        """When neither timestamp is provided, updated is None."""
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(daily, {})
        assert result[0]["updated"] is None

    def test_updated_falls_back_to_ec_only(self) -> None:
        """When only EC timestamp provided, updated = EC."""
        daily = [_daily_item("Monday", "2026-03-23")]
        result = merge_weong_into_daily(
            daily, {},
            ec_updated="2026-03-23T14:00:00+00:00",
        )
        assert result[0]["updated"] == "2026-03-23T14:00:00+00:00"

    def test_updated_falls_back_to_weong_only(self) -> None:
        """When only WEonG timestamp provided, updated = WEonG."""
        daily = [_daily_item("Monday", "2026-03-23")]
        weong_periods = {
            ("2026-03-23", "day"): _weong_period(pop=30),
            ("2026-03-23", "night"): _weong_period(pop=20),
        }
        result = merge_weong_into_daily(
            daily, weong_periods,
            weong_updated="2026-03-23T12:00:00+00:00",
        )
        assert result[0]["updated"] == "2026-03-23T12:00:00+00:00"


# ---------------------------------------------------------------------------
# _filter_past_hours on daily timesteps
# ---------------------------------------------------------------------------

class TestFilterPastHoursOnTimesteps:
    @freeze_time("2026-03-23T15:30:00Z")
    def test_past_timesteps_filtered(self):
        """Given frozen time at 15:30 → timesteps before 15:00 removed."""
        timesteps = [
            {"time": "2026-03-23T13:00:00Z", "temp": -5},
            {"time": "2026-03-23T14:00:00Z", "temp": -4},
            {"time": "2026-03-23T15:00:00Z", "temp": -3},
            {"time": "2026-03-23T16:00:00Z", "temp": -2},
        ]

        result = filter_past_hours(timesteps)

        assert len(result) == 2
        assert result[0]["time"] == "2026-03-23T15:00:00Z"
        assert result[1]["time"] == "2026-03-23T16:00:00Z"

    @freeze_time("2026-03-23T15:30:00Z")
    def test_current_hour_kept(self):
        """Given timestep at current hour (15:00) → kept in result."""
        timesteps = [
            {"time": "2026-03-23T15:00:00Z", "temp": -3},
        ]

        result = filter_past_hours(timesteps)

        assert len(result) == 1
        assert result[0]["time"] == "2026-03-23T15:00:00Z"

    @freeze_time("2026-03-23T23:30:00Z")
    def test_night_timesteps_filtered(self):
        """Given frozen time at 23:30 → night timesteps before 23:00 removed."""
        timesteps = [
            {"time": "2026-03-23T21:00:00Z", "temp": -8},
            {"time": "2026-03-23T22:00:00Z", "temp": -9},
            {"time": "2026-03-23T23:00:00Z", "temp": -10},
            {"time": "2026-03-24T00:00:00Z", "temp": -11},
        ]

        result = filter_past_hours(timesteps)

        assert len(result) == 2
        assert result[0]["time"] == "2026-03-23T23:00:00Z"
        assert result[1]["time"] == "2026-03-24T00:00:00Z"
