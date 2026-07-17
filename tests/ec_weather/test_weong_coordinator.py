"""Tests for ECWEonGCoordinator — WEonG business logic and aggregation."""

import asyncio
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from freezegun import freeze_time

from ec_weather.const import WEONG_CACHE_TTL_HRDPS, WEONG_CACHE_TTL_RDPS
from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.weong_helpers import (
    _HRDPS_PREFIX,
    _RDPS_PREFIX,
    _LAYER_SUFFIXES,
    _model_from_layer,
    _models_for_day,
    _weong_layer_name,
    build_periods,
)
from ec_weather.transforms import derive_icon, merge_weong_into_daily

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
    prefix = _HRDPS_PREFIX if model == "hrdps" else _RDPS_PREFIX

    for i, ts in enumerate(timesteps):
        # POP
        pop = pop_values[i] if i < len(pop_values) else None
        layer = f"{prefix}{_LAYER_SUFFIXES['precip_prob']}"
        results.append((layer, ts, period_key, pop))

        # AirTemp
        temp = None
        if temp_values and i < len(temp_values):
            temp = temp_values[i]
        layer = f"{prefix}{_LAYER_SUFFIXES['air_temp']}"
        results.append((layer, ts, period_key, temp))

        # Rain
        if rain_values and i < len(rain_values) and rain_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['rain_amt']}"
            results.append((layer, ts, period_key, rain_values[i]))

        # Snow
        if snow_values and i < len(snow_values) and snow_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['snow_amt']}"
            results.append((layer, ts, period_key, snow_values[i]))

        # Freezing precip
        if freezing_values and i < len(freezing_values) and freezing_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['freezing_precip_amt']}"
            results.append((layer, ts, period_key, freezing_values[i]))

        # Ice pellets
        if ice_values and i < len(ice_values) and ice_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['ice_pellet_amt']}"
            results.append((layer, ts, period_key, ice_values[i]))

        # Sky state
        if sky_values and i < len(sky_values) and sky_values[i] is not None:
            layer = f"{prefix}{_LAYER_SUFFIXES['sky_state']}"
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

    def test_period_rain_is_expected_value_of_timesteps(self, hass: HomeAssistant):
        """Period rain is the probability-weighted expected total (in mm).

        UPDATED (was test_period_rain_is_sum_of_timesteps, asserting the naive
        4.5 mm sum of the CONDITIONAL per-hour amounts). The amounts are
        "rain GIVEN precip that hour", so the period total is now the expected
        value: (pop/100) * amount per step, summed.
        """
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
        # Expected: 0.5*(1.0 + 2.0 + 1.5) = 2.25 -> 2.2 mm
        assert result["rain_mm"] == 2.2

    def test_period_snow_is_expected_value_of_timesteps(self, hass: HomeAssistant):
        """Period snow is the probability-weighted expected total (in cm).

        UPDATED (was test_period_snow_is_sum_of_timesteps, asserting the naive
        6.0 cm sum). Now the expected value: (pop/100) * amount per step.
        """
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
        # Expected: 0.5*(2.0 + 3.0 + 1.0) = 3.0 cm
        assert result["snow_cm"] == 3.0

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
        # UPDATED for expected-value math (was 4.0 mm sum). Freezing precip
        # folds into rain, then probability-weighted: 0.8*(2.5 + 1.5) = 3.2 mm.
        assert result["rain_mm"] == 3.2
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
        # UPDATED for expected-value math (was 0.8 cm sum). Ice pellets fold
        # into snow, then probability-weighted: 0.7*(0.5 + 0.3) = 0.56 -> 0.6 cm.
        assert result["snow_cm"] == 0.6
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
    """Tests that RDPS and HRDPS timestep generation is correct."""

    @freeze_time("2026-03-22T12:00:00Z")
    def test_rdps_far_day_timesteps_are_hourly(self, hass: HomeAssistant):
        """RDPS far-day timesteps are hourly (no 3h snapping)."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_weong_coordinator(hass)
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        # Day 3 (2026-03-25) is RDPS-only and inside the 84h horizon.
        day3_periods = [p for p in periods if p[0] == "2026-03-25"]
        timestep_info = coord._build_timestep_info(day3_periods, today)

        rdps_steps = [ts for ts, _, model in timestep_info if model == "rdps"]
        assert rdps_steps, "Day 3 should generate RDPS timesteps"
        assert all(m == "rdps" for _, _, m in timestep_info)

        # Consecutive RDPS timesteps must be exactly 1h apart — no 3h snapping.
        ordered = sorted(rdps_steps)
        for earlier, later in zip(ordered, ordered[1:]):
            assert later - earlier == timedelta(hours=1), (
                f"RDPS timesteps must be hourly, got gap {later - earlier}"
            )

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


# ---------------------------------------------------------------------------
# Tier 1 — RDPS-WEonG (resurrected far-day model path)
# ---------------------------------------------------------------------------

def _daily_stub(period: str, date_str: str) -> dict:
    """Minimal daily forecast item for merge_weong_into_daily."""
    return {
        "period": period,
        "date": date_str,
        "temp_high": 1,
        "temp_low": -10,
        "icon_code": 16,
        "icon_code_night": 38,
        "condition_day": "Snow",
        "condition_night": "Cloudy periods",
        "text_summary_day": "Snow. High 1.",
        "text_summary_night": "Cloudy. Low minus 10.",
    }


class TestRdpsLayerNames:
    """RDPS layer names are bare (no .3h suffix); HRDPS keeps its prefix."""

    def test_rdps_layer_name_has_no_3h_suffix(self):
        """Plan test 1: rdps layer is 'RDPS-WEonG_10km_<suffix>' with no .3h."""
        assert (
            _weong_layer_name("Precip-Prob", "rdps")
            == "RDPS-WEonG_10km_Precip-Prob"
        )

    def test_rdps_layer_names_never_carry_3h(self):
        """Every logical suffix builds a bare RDPS layer name."""
        for suffix in _LAYER_SUFFIXES.values():
            layer = _weong_layer_name(suffix, "rdps")
            assert layer == f"RDPS-WEonG_10km_{suffix}"
            assert ".3h" not in layer

    def test_hrdps_layer_name_unchanged(self):
        """HRDPS layer names keep the 2.5km prefix and no suffix."""
        assert (
            _weong_layer_name("Precip-Prob", "hrdps")
            == "HRDPS-WEonG_2.5km_Precip-Prob"
        )


class TestRdpsModelsForDay:
    """Plan test 2: day-to-model mapping. WEonG hourly, GEPS 3-hourly (days 4-6)."""

    def test_days_0_1_hrdps_only(self):
        assert _models_for_day(0) == [("hrdps", 1)]
        assert _models_for_day(1) == [("hrdps", 1)]

    def test_day_2_dual_model_rdps_hourly(self):
        assert _models_for_day(2) == [("hrdps", 1), ("rdps", 1)]

    def test_day_3_rdps_only(self):
        assert _models_for_day(3) == [("rdps", 1)]

    def test_day_4_rdps_plus_geps(self):
        # Day 4 straddles the 84h cap: RDPS to the cap, GEPS for the remainder.
        assert _models_for_day(4) == [("rdps", 1), ("geps", 3)]

    def test_days_5_6_geps_only(self):
        assert _models_for_day(5) == [("geps", 3)]
        assert _models_for_day(6) == [("geps", 3)]

    def test_weong_models_are_hourly_geps_is_three_hourly(self):
        """WEonG (HRDPS/RDPS) steps are 1h; GEPS steps are 3h."""
        for days_ahead in range(7):
            for model, step_hours in _models_for_day(days_ahead):
                if model == "geps":
                    assert step_hours == 3, f"GEPS day {days_ahead} must be 3-hourly"
                else:
                    assert step_hours == 1, (
                        f"day {days_ahead} model {model} must be hourly"
                    )


class TestRdpsModelFromLayer:
    """Plan test 4: model detection round-trips for both prefixes."""

    def test_model_from_hrdps_layer(self):
        assert _model_from_layer("HRDPS-WEonG_2.5km_AirTemp") == "hrdps"

    def test_model_from_rdps_layer(self):
        assert _model_from_layer("RDPS-WEonG_10km_AirTemp") == "rdps"

    def test_round_trip_both_models(self):
        for model in ("hrdps", "rdps"):
            layer = _weong_layer_name(_LAYER_SUFFIXES["air_temp"], model)
            assert _model_from_layer(layer) == model


class TestRdpsCacheTtl:
    """Plan test 5: cache TTL selection keys on the model prefix."""

    def test_rdps_layer_uses_rdps_ttl(self, hass: HomeAssistant):
        coord = _make_weong_coordinator(hass)
        rdps_layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], "rdps")
        assert coord._cache_ttl(rdps_layer) == WEONG_CACHE_TTL_RDPS

    def test_hrdps_layer_uses_hrdps_ttl(self, hass: HomeAssistant):
        coord = _make_weong_coordinator(hass)
        hrdps_layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], "hrdps")
        assert coord._cache_ttl(hrdps_layer) == WEONG_CACHE_TTL_HRDPS


class TestRdpsHorizonCap:
    """Plan test 3: timesteps stop at model_run + 84h; far days stay honest."""

    @freeze_time("2026-07-07T12:00:00Z")
    def test_no_timesteps_generated_past_84h(self, hass: HomeAssistant):
        """Timestep generation yields nothing after expected_run + 84h."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_weong_coordinator(hass)
        today = date(2026, 7, 7)
        now_utc = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        timestep_info = coord._build_timestep_info(periods, today)

        # Expected model run at 12:00Z is the 06Z run (06 + 2h delay = 08Z passed).
        # Cap = 2026-07-07T06:00Z + 84h = 2026-07-10T18:00Z.
        horizon_cap = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
        assert timestep_info, "Near days should still generate timesteps"
        for timestep, _period_key, _model in timestep_info:
            assert timestep <= horizon_cap, (
                f"timestep {timestep} exceeds 84h horizon cap {horizon_cap}"
            )

    @freeze_time("2026-07-07T12:00:00Z")
    def test_day_wholly_past_cap_generates_nothing(self, hass: HomeAssistant):
        """Day 5 (2026-07-12) lies entirely past the cap → zero timesteps."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_weong_coordinator(hass)
        today = date(2026, 7, 7)
        now_utc = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        timestep_info = coord._build_timestep_info(periods, today)

        day5 = [t for t, pk, _ in timestep_info if pk[0] == "2026-07-12"]
        assert day5 == [], "Day 5 is past the 84h horizon; expected no timesteps"

    def test_far_day_empty_but_fetched_is_unavailable(self, hass: HomeAssistant):
        """A far day marked completed with zero timesteps → 'unavailable'.

        The horizon cap produces no timesteps for days 5-6, but the day is
        still attempted (enters _completed_days), so transforms keeps the
        honest 'unavailable' state (not 'pending').
        """
        coord = _make_weong_coordinator(hass)
        far_date = "2026-07-12"
        utc_start = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)
        periods = _make_periods(far_date, "day", utc_start, utc_end)

        coord._completed_days.add(far_date)
        output = coord._project_output(periods)
        assert far_date in output["days_fetched"]

        daily = [_daily_stub("Sunday", far_date)]
        merged = merge_weong_into_daily(
            daily, output["periods"], days_fetched=output["days_fetched"],
        )
        assert merged[0]["timesteps_state"] == "unavailable"


class TestRdpsInvalidLayerRegression:
    """Plan test 6: the GDPS-WEonG death mode (no data) degrades honestly."""

    def test_all_none_results_no_crash_and_unavailable(self, hass: HomeAssistant):
        """All-None query results (InvalidLayersParameter death mode) must not
        crash, must leave the store empty, and the attempted day is unavailable.
        """
        coord = _make_weong_coordinator(hass)
        far_date = "2026-07-12"
        timestep = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
        period_key = (far_date, "day")
        layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], "rdps")

        all_none_results = [(layer, timestep, period_key, None)]
        failed_count = coord._results_to_store(all_none_results)

        assert failed_count == 1
        assert len(coord._store) == 0  # no entries created, no crash

        coord._completed_days.add(far_date)
        utc_start = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
        utc_end = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)
        output = coord._project_output(
            _make_periods(far_date, "day", utc_start, utc_end),
        )
        daily = [_daily_stub("Sunday", far_date)]
        merged = merge_weong_into_daily(
            daily, output["periods"], days_fetched=output["days_fetched"],
        )
        assert merged[0]["timesteps_state"] == "unavailable"
