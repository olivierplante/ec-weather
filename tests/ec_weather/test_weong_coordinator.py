"""Tests for ECWEonGCoordinator — WEonG business logic and aggregation."""

import asyncio
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.weong_helpers import (
    _HRDPS_PREFIX,
    _GDPS_PREFIX,
    _LAYER_SUFFIXES,
    _weong_layer_name,
    build_periods,
)
from ec_weather.transforms import derive_icon

from .conftest import MOCK_CONFIG_DATA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/Toronto")


def _make_weong_coordinator(hass: HomeAssistant) -> ECWEonGCoordinator:
    """Create a WEonG coordinator with mock config."""
    return ECWEonGCoordinator(
        hass,
        geomet_bbox=MOCK_CONFIG_DATA["geomet_bbox"],
    )


def _build_all_results(
    period_key: tuple[str, str],
    timesteps: list[datetime],
    pop_values: list[float | None],
    rain_values: list[float | None] | None = None,
    snow_values: list[float | None] | None = None,
    freezing_values: list[float | None] | None = None,
    ice_values: list[float | None] | None = None,
    sky_values: list[float | None] | None = None,
    temp_values: list[float | None] | None = None,
    model: str = "hrdps",
) -> list[tuple[str, datetime, tuple[str, str], float | None]]:
    """Build a flat all_results list for store + project tests.

    Each entry is (layer_name, timestep, period_key, value).
    """
    results = []
    prefix = _HRDPS_PREFIX if model == "hrdps" else _GDPS_PREFIX
    suffix_3h = ".3h" if model == "gdps" else ""

    for i, ts in enumerate(timesteps):
        # POP
        pop = pop_values[i] if i < len(pop_values) else None
        layer = f"{prefix}{_LAYER_SUFFIXES['precip_prob']}{suffix_3h}"
        results.append((layer, ts, period_key, pop))

        # AirTemp
        temp = None
        if temp_values and i < len(temp_values):
            temp = temp_values[i]
        layer = f"{prefix}{_LAYER_SUFFIXES['air_temp']}{suffix_3h}"
        results.append((layer, ts, period_key, temp))

        # Rain
        if rain_values and i < len(rain_values) and rain_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['rain_amt']}{suffix_3h}"
            results.append((layer, ts, period_key, rain_values[i]))

        # Snow
        if snow_values and i < len(snow_values) and snow_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['snow_amt']}{suffix_3h}"
            results.append((layer, ts, period_key, snow_values[i]))

        # Freezing precip
        if freezing_values and i < len(freezing_values) and freezing_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['freezing_precip_amt']}{suffix_3h}"
            results.append((layer, ts, period_key, freezing_values[i]))

        # Ice pellets
        if ice_values and i < len(ice_values) and ice_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['ice_pellet_amt']}{suffix_3h}"
            results.append((layer, ts, period_key, ice_values[i]))

        # Sky state
        if sky_values and i < len(sky_values) and sky_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['sky_state']}{suffix_3h}"
            results.append((layer, ts, period_key, sky_values[i]))

    return results


def _make_periods(
    date_str: str, period_type: str, utc_start: datetime, utc_end: datetime,
) -> list[tuple[str, str, datetime, datetime]]:
    """Build a minimal periods list for store + project tests."""
    return [(date_str, period_type, utc_start, utc_end)]


def _make_timesteps(utc_start: datetime, count: int, step_hours: int = 1) -> list[datetime]:
    """Generate a list of UTC timesteps."""
    return [utc_start + timedelta(hours=i * step_hours) for i in range(count)]


def _aggregate_via_store(coord, all_results, periods):
    """Test helper: merge results into store and project output.

    Replaces the old coord._aggregate_results() convenience method.
    """
    coord._results_to_store(all_results)
    return coord._project_output(periods)


# ---------------------------------------------------------------------------
# Period aggregation tests
# ---------------------------------------------------------------------------

class TestPeriodAggregation:
    """Tests for store + project business logic on period-level data."""

    def test_period_pop_is_max_of_timesteps(self, hass: HomeAssistant):
        """Given POP values [10, 30, 60, 20], period POP = 60 (max)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 4)
        pop_values = [10.0, 30.0, 60.0, 20.0]

        all_results = _build_all_results(period_key, timesteps, pop_values)
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        assert output["periods"][period_key]["pop"] == 60

    def test_period_rain_is_sum_of_timesteps(self, hass: HomeAssistant):
        """Given rain amounts across timesteps, period rain = sum (in mm)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 3)
        pop_values = [50.0, 50.0, 50.0]
        # rain_amt layer returns values in meters; x1000 = mm
        rain_m = [0.001, 0.002, 0.0015]  # 1mm, 2mm, 1.5mm

        all_results = _build_all_results(
            period_key, timesteps, pop_values, rain_values=rain_m,
        )
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        result = output["periods"][period_key]
        # Sum: 1.0 + 2.0 + 1.5 = 4.5 mm
        assert result["rain_mm"] == 4.5

    def test_period_snow_is_sum_of_timesteps(self, hass: HomeAssistant):
        """Given snow amounts across timesteps, period snow = sum (in cm)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 3)
        pop_values = [50.0, 50.0, 50.0]
        # snow_amt layer returns values in meters; x100 = cm
        snow_m = [0.02, 0.03, 0.01]  # 2cm, 3cm, 1cm

        all_results = _build_all_results(
            period_key, timesteps, pop_values, snow_values=snow_m,
        )
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        result = output["periods"][period_key]
        # Sum: 2.0 + 3.0 + 1.0 = 6.0 cm
        assert result["snow_cm"] == 6.0

    def test_no_precip_gives_null_amounts(self, hass: HomeAssistant):
        """Given POP=0 everywhere, rain/snow amounts = None."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 4)
        pop_values = [0.0, 0.0, 0.0, 0.0]

        all_results = _build_all_results(period_key, timesteps, pop_values)
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        result = output["periods"][period_key]
        assert result["rain_mm"] is None
        assert result["snow_cm"] is None

    def test_freezing_precip_folds_to_rain_mm(self, hass: HomeAssistant):
        """FreezingPrecipCondAmt folds into rain_amt_mm (x1 since already mm)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 2)
        pop_values = [80.0, 80.0]
        # FreezingPrecipCondAmt returns mm directly (x1)
        freezing_mm = [2.5, 1.5]

        all_results = _build_all_results(
            period_key, timesteps, pop_values, freezing_values=freezing_mm,
        )
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        result = output["periods"][period_key]
        # Freezing precip folds into rain: 2.5 + 1.5 = 4.0 mm
        assert result["rain_mm"] == 4.0
        # No snow from freezing precip
        assert result["snow_cm"] is None

    def test_ice_pellets_fold_to_snow_cm(self, hass: HomeAssistant):
        """IcePelletsCondAmt folds into snow_amt_cm (x100 m->cm conversion)."""
        coord = _make_weong_coordinator(hass)
        utc_start = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-22", "day")
        timesteps = _make_timesteps(utc_start, 2)
        pop_values = [70.0, 70.0]
        # IcePelletsCondAmt returns meters; x100 = cm
        ice_m = [0.005, 0.003]  # 0.5cm, 0.3cm

        all_results = _build_all_results(
            period_key, timesteps, pop_values, ice_values=ice_m,
        )
        periods = _make_periods("2026-03-22", "day", utc_start, utc_end)

        output = _aggregate_via_store(coord, all_results, periods)
        result = output["periods"][period_key]
        # Ice pellets fold into snow: 0.5 + 0.3 = 0.8 cm
        assert result["snow_cm"] == 0.8
        # No rain from ice pellets
        assert result["rain_mm"] is None


# ---------------------------------------------------------------------------
# _derive_icon tests (pure function from sensor.py)
# ---------------------------------------------------------------------------

class TestDeriveIcon:
    """Tests for _derive_icon — icon derivation from WEonG data."""

    def test_sky_state_clear_day_icon(self):
        """sky_state=1, hour=14 -> icon_code=0 (sunny daytime variant, sky<=2)."""
        weong = {"sky_state": 1.0}
        icon_code, condition = derive_icon(weong, hour=14)
        assert icon_code == 0
        assert condition == "Sunny"

    def test_sky_state_clear_night_icon(self):
        """sky_state=1, hour=22 -> icon_code=30 (clear night variant, sky<=2)."""
        weong = {"sky_state": 1.0}
        icon_code, condition = derive_icon(weong, hour=22)
        assert icon_code == 30
        assert condition == "Clear"

    def test_sky_state_cloudy_icon(self):
        """sky_state=9 -> icon_code=10 (cloudy, same day/night)."""
        weong = {"sky_state": 9.0}
        icon_code, condition = derive_icon(weong, hour=14)
        assert icon_code == 10
        assert condition == "Cloudy"

    def test_precip_icon_overrides_sky_state(self):
        """rain>0 + sky_state=0 -> icon=12 (rain), not sunny."""
        weong = {"rain_mm": 2.0, "sky_state": 0.0}
        icon_code, condition = derive_icon(weong, hour=14)
        assert icon_code == 12
        assert condition == "Rain"


# ---------------------------------------------------------------------------
# build_periods tests
# ---------------------------------------------------------------------------

class TestBuildPeriods:
    """Tests for build_periods — day/night period generation with UTC boundaries."""

    def test_day_night_boundaries_utc(self, hass: HomeAssistant):
        """build_periods creates correct UTC boundaries for local 06:00/18:00.

        America/Toronto is UTC-5 (EST) or UTC-4 (EDT).
        On 2026-03-22 (after spring-forward), EDT applies (UTC-4).
        Local 06:00 EDT = 10:00 UTC, local 18:00 EDT = 22:00 UTC.
        """
        hass.config.time_zone = "America/Toronto"
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)

        # Find the first day period for 2026-03-22
        day_period = None
        night_period = None
        for date_str, ptype, utc_start, utc_end in periods:
            if date_str == "2026-03-22" and ptype == "day":
                day_period = (utc_start, utc_end)
            if date_str == "2026-03-22" and ptype == "night":
                night_period = (utc_start, utc_end)

        assert day_period is not None
        # EDT = UTC-4: local 06:00 = 10:00 UTC, local 18:00 = 22:00 UTC
        assert day_period[0].hour == 10
        assert day_period[1].hour == 22

        assert night_period is not None
        # Night: local 18:00 = 22:00 UTC, next day 06:00 = 10:00 UTC
        assert night_period[0].hour == 22
        assert night_period[1].hour == 10


# ---------------------------------------------------------------------------
# Timestep alignment tests
# ---------------------------------------------------------------------------

class TestTimestepAlignment:
    """Tests that GDPS and HRDPS timestep generation is correct."""

    def test_gdps_timesteps_on_3h_boundaries(self, hass: HomeAssistant):
        """GDPS timesteps must align to 00,03,06,...,21 UTC boundaries."""
        hass.config.time_zone = "America/Toronto"
        # Day 3 (GDPS only): today + 3 days
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)

        # Get the day period for day+3 (2026-03-25)
        target_date = "2026-03-25"
        day_period = None
        for date_str, ptype, utc_start, utc_end in periods:
            if date_str == target_date and ptype == "day":
                day_period = (utc_start, utc_end)
                break

        assert day_period is not None
        utc_start, utc_end = day_period

        # Simulate GDPS timestep generation (same logic as _async_update_data)
        h = utc_start.hour
        remainder = h % 3
        if remainder == 0:
            t = utc_start.replace(minute=0, second=0, microsecond=0)
        else:
            t = (utc_start.replace(minute=0, second=0, microsecond=0)
                 + timedelta(hours=3 - remainder))

        timesteps = []
        while t < utc_end:
            timesteps.append(t)
            t += timedelta(hours=3)

        # All timesteps must be on 3h boundaries
        for ts in timesteps:
            assert ts.hour % 3 == 0, f"GDPS timestep {ts} not on 3h boundary"

        # Should have at least 1 timestep
        assert len(timesteps) >= 1

    def test_hrdps_timesteps_hourly(self, hass: HomeAssistant):
        """HRDPS timesteps are hourly (1h apart)."""
        hass.config.time_zone = "America/Toronto"
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)

        # Get the day period for today (HRDPS)
        day_period = None
        for date_str, ptype, utc_start, utc_end in periods:
            if date_str == "2026-03-22" and ptype == "day":
                day_period = (utc_start, utc_end)
                break

        assert day_period is not None
        utc_start, utc_end = day_period

        # HRDPS: start at utc_start, step 1h
        timesteps = []
        t = utc_start
        while t < utc_end:
            timesteps.append(t)
            t += timedelta(hours=1)

        # Verify consecutive timesteps are 1h apart
        for i in range(1, len(timesteps)):
            delta = timesteps[i] - timesteps[i - 1]
            assert delta == timedelta(hours=1), (
                f"HRDPS timestep gap {delta} between {timesteps[i-1]} and {timesteps[i]}"
            )

        # Day period is 12h (06:00-18:00 local), so 12 hourly timesteps
        assert len(timesteps) == 12


# ---------------------------------------------------------------------------
# _query_feature_info timeout test
# ---------------------------------------------------------------------------

@pytest.mark.enable_socket
class TestQueryFeatureInfo:
    """Tests for _query_feature_info edge cases."""

    async def test_geomet_timeout_returns_transient_error(self, hass: HomeAssistant, aioclient_mock):
        """_query_feature_info returns _TRANSIENT_ERROR on timeout (not cached)."""
        coord = _make_weong_coordinator(hass)
        timestep = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], "hrdps")

        # Mock the GeoMet URL to raise a timeout
        aioclient_mock.get(
            "https://geo.weather.gc.ca/geomet",
            exc=asyncio.TimeoutError(),
        )

        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        session = async_get_clientsession(hass)
        result = await coord._query_feature_info(session, layer, timestep)

        # Should return transient error sentinel, NOT None
        assert result is coord._TRANSIENT_ERROR
