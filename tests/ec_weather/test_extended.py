"""Tests for the GEPS extended-forecast wave (phase B).

specs/ec_weather/weong-far-days-plan.md phase B: the extended coordinator wave
that brings days 4-6 popup timesteps back for everyone via the GEPS ensemble.

Covers:
  - extended.py pure planning helpers (3h grid, 12h window mapping, wet-gating,
    query plans, folding raw values into TimestepData + precip_windows)
  - ECWEonGCoordinator integration (_fetch_geps_day, cache TTL, WEonG path skips
    GEPS, precip_windows projection, on-demand GEPS fetch)
  - the daily-forecast contract guard: the first 7 entries keep their exact key
    set; only geps days may add the additive precip_windows key

All GEPS values here are synthetic (repo policy) — never captured live data.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from ec_weather.const import CACHE_TTL_GEPS
from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.extended import (
    EXTENDED_FIRST_DAY,
    EXTENDED_LAST_DAY,
    GEPS_QUERY_TAG,
    align_to_geps_grid,
    build_geps_timesteps,
    build_precip_window,
    build_precip_windows,
    days_ahead_for,
    expected_geps_run,
    geps_timesteps_for_periods,
    geps_windows_for_periods,
    is_geps_day,
    plan_base_queries,
    plan_pop_queries,
    plan_wet_queries,
    wet_window_ends,
)
from ec_weather.coordinator.extended import (
    build_outlook_entry,
    is_outlook_day,
    nearest_geps_step,
    outlook_dates,
    outlook_days_ahead,
    outlook_sample_points,
    plan_outlook_base_queries,
)
from ec_weather.coordinator.extended_helpers import (
    GEPS_AMOUNT_P25,
    GEPS_AMOUNT_P75,
    GEPS_CLOUD_P50,
    GEPS_HUMIDEX_P50,
    GEPS_POP_12H,
    GEPS_RAIN_MEDIAN,
    GEPS_SNOW_MEDIAN,
    GEPS_TEMPERATURE_P25,
    GEPS_TEMPERATURE_P50,
    GEPS_TEMPERATURE_P75,
)
from ec_weather.icon_registry import (
    MOSTLY_CLOUDY_DAY,
    MOSTLY_CLOUDY_NIGHT,
    PARTLY_CLOUDY_NIGHT,
    RAIN,
)

_MOSTLY_CLOUDY = {MOSTLY_CLOUDY_DAY, MOSTLY_CLOUDY_NIGHT}
# "Chance of" EC icon codes (rain-dominant -> chance of showers).
_CHANCE_OF_SHOWERS = 6
from ec_weather.transforms import merge_weong_into_daily

from .conftest import MOCK_CONFIG_DATA

ET = ZoneInfo("America/Toronto")
TODAY = date(2026, 7, 7)


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _make_coord(hass: HomeAssistant) -> ECWEonGCoordinator:
    return ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])


# Day 5 (2026-07-12) EDT (UTC-4) periods: day 10-22Z, night 22Z -> 10Z next day.
DAY5_PERIODS = [
    ("2026-07-12", "day", _utc(2026, 7, 12, 10), _utc(2026, 7, 12, 22)),
    ("2026-07-12", "night", _utc(2026, 7, 12, 22), _utc(2026, 7, 13, 10)),
]


# ---------------------------------------------------------------------------
# Coverage + scheduling helpers
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_is_geps_day_band(self):
        assert not is_geps_day(3)
        assert is_geps_day(4)
        assert is_geps_day(5)
        assert is_geps_day(6)
        assert not is_geps_day(7)
        assert (EXTENDED_FIRST_DAY, EXTENDED_LAST_DAY) == (4, 6)

    def test_days_ahead_for(self):
        assert days_ahead_for("2026-07-11", TODAY) == 4
        assert days_ahead_for("2026-07-12", TODAY) == 5
        # Past dates clamp to 0, never negative.
        assert days_ahead_for("2026-07-01", TODAY) == 0


class TestExpectedGepsRun:
    @pytest.mark.parametrize(
        "now,expected",
        [
            # 12Z run publishes ~18Z; at 18Z it's the current run.
            (_utc(2026, 7, 7, 18), _utc(2026, 7, 7, 12)),
            # At 17Z the 12Z run isn't out yet -> 00Z run.
            (_utc(2026, 7, 7, 17), _utc(2026, 7, 7, 0)),
            # Early morning before the 00Z run publishes -> yesterday's 12Z.
            (_utc(2026, 7, 7, 3), _utc(2026, 7, 6, 12)),
        ],
    )
    def test_run_at_00z_12z_with_lag(self, now, expected):
        assert expected_geps_run(now) == expected


# ---------------------------------------------------------------------------
# 3h grid + window mapping
# ---------------------------------------------------------------------------

class TestAlignToGepsGrid:
    @pytest.mark.parametrize(
        "moment,expected",
        [
            (_utc(2026, 7, 12, 12), _utc(2026, 7, 12, 12)),  # on grid -> unchanged
            (_utc(2026, 7, 12, 10), _utc(2026, 7, 12, 12)),  # 10 -> 12
            (_utc(2026, 7, 12, 22), _utc(2026, 7, 13, 0)),   # 22 -> next 00
            (_utc(2026, 7, 12, 13), _utc(2026, 7, 12, 15)),  # 13 -> 15
            (_utc(2026, 7, 12, 10, 30), _utc(2026, 7, 12, 12)),  # sub-hour rounds up
        ],
    )
    def test_ceils_to_three_hour_grid(self, moment, expected):
        assert align_to_geps_grid(moment) == expected


class TestGepsTimestepsForPeriods:
    def test_three_hour_aligned_within_periods(self):
        steps = geps_timesteps_for_periods(DAY5_PERIODS)
        assert steps == [
            _utc(2026, 7, 12, 12), _utc(2026, 7, 12, 15),
            _utc(2026, 7, 12, 18), _utc(2026, 7, 12, 21),
            _utc(2026, 7, 13, 0), _utc(2026, 7, 13, 3),
            _utc(2026, 7, 13, 6), _utc(2026, 7, 13, 9),
        ]

    def test_all_steps_on_three_hour_grid(self):
        for step in geps_timesteps_for_periods(DAY5_PERIODS):
            assert step.hour % 3 == 0


class TestGepsWindowsForPeriods:
    def test_one_window_per_half_via_midpoint(self):
        windows = geps_windows_for_periods(DAY5_PERIODS)
        assert len(windows) == 2
        day, night = windows
        assert day["period_type"] == "day"
        assert (day["start"], day["end"]) == (_utc(2026, 7, 12, 12), _utc(2026, 7, 13, 0))
        assert night["period_type"] == "night"
        assert (night["start"], night["end"]) == (_utc(2026, 7, 13, 0), _utc(2026, 7, 13, 12))


# ---------------------------------------------------------------------------
# Wet-gating + band payload
# ---------------------------------------------------------------------------

class TestWetWindowEnds:
    def test_gate_at_thirty(self):
        pop = {
            _utc(2026, 7, 12, 12): 60,
            _utc(2026, 7, 13, 0): 30,   # exactly 30 counts
            _utc(2026, 7, 13, 12): 29,  # below gate
        }
        assert wet_window_ends(pop) == [_utc(2026, 7, 12, 12), _utc(2026, 7, 13, 0)]

    def test_none_pop_never_wet(self):
        assert wet_window_ends({_utc(2026, 7, 12, 12): None}) == []


class TestBuildPrecipWindow:
    def test_wet_window_shape(self):
        window = build_precip_window(
            _utc(2026, 7, 12, 12), _utc(2026, 7, 13, 0), 55.6, 4.0, 9.0,
        )
        assert window == {
            "start": "2026-07-12T12:00:00Z",
            "end": "2026-07-13T00:00:00Z",
            "pop": 56,          # rounded
            "amount_p25": 4.0,
            "amount_p75": 9.0,
        }

    def test_dry_window_has_no_amounts(self):
        window = build_precip_window(
            _utc(2026, 7, 12, 12), _utc(2026, 7, 13, 0), 10, None, None,
        )
        assert window["pop"] == 10
        assert window["amount_p25"] is None
        assert window["amount_p75"] is None


# ---------------------------------------------------------------------------
# Query plans + folding
# ---------------------------------------------------------------------------

class TestQueryPlans:
    def test_base_queries_three_layers_per_step(self):
        steps = [_utc(2026, 7, 12, 12), _utc(2026, 7, 12, 15)]
        queries = plan_base_queries(steps)
        assert len(queries) == 6
        layers_at_first = {layer for layer, ts, _ in queries if ts == steps[0]}
        assert layers_at_first == {GEPS_TEMPERATURE_P50, GEPS_HUMIDEX_P50, GEPS_CLOUD_P50}
        assert all(key == GEPS_QUERY_TAG for _, _, key in queries)

    def test_pop_queries_one_per_window(self):
        ends = [_utc(2026, 7, 12, 12), _utc(2026, 7, 13, 0)]
        queries = plan_pop_queries(ends)
        assert [layer for layer, _, _ in queries] == [GEPS_POP_12H, GEPS_POP_12H]

    def test_wet_queries_amount_band_plus_type(self):
        queries = plan_wet_queries([_utc(2026, 7, 12, 12)])
        assert {layer for layer, _, _ in queries} == {
            GEPS_AMOUNT_P25, GEPS_AMOUNT_P75, GEPS_RAIN_MEDIAN, GEPS_SNOW_MEDIAN,
        }


class TestBuildGepsTimesteps:
    def test_pop_from_covering_window_and_model_geps(self):
        steps = [_utc(2026, 7, 12, 15), _utc(2026, 7, 13, 3)]
        pop_by_window_end = {
            _utc(2026, 7, 13, 0): 60,   # covers 15Z
            _utc(2026, 7, 13, 12): 20,  # covers 03Z next day
        }
        values = {
            (GEPS_TEMPERATURE_P50, steps[0]): 21.4,
            (GEPS_CLOUD_P50, steps[0]): 70.0,
            (GEPS_RAIN_MEDIAN, _utc(2026, 7, 13, 0)): 5.0,
            (GEPS_SNOW_MEDIAN, _utc(2026, 7, 13, 0)): 0.0,
            (GEPS_TEMPERATURE_P50, steps[1]): 12.0,
            (GEPS_CLOUD_P50, steps[1]): 70.0,
        }
        entries = build_geps_timesteps(steps, pop_by_window_end, values)
        assert [e.model for e in entries] == ["geps", "geps"]
        assert entries[0].temp == 21.4
        assert entries[0].pop == 60
        assert entries[0].icon_code == RAIN          # wet window, rain-dominant
        assert entries[1].pop == 20
        # Dry window -> NT cloud bucket; 03Z is night, so the night variant.
        assert entries[1].icon_code == MOSTLY_CLOUDY_NIGHT


class TestBuildPrecipWindows:
    def test_two_entries_one_per_half(self):
        half_windows = geps_windows_for_periods(DAY5_PERIODS)
        pop_by_window_end = {
            _utc(2026, 7, 13, 0): 60,
            _utc(2026, 7, 13, 12): 10,
        }
        values = {
            (GEPS_AMOUNT_P25, _utc(2026, 7, 13, 0)): 4.0,
            (GEPS_AMOUNT_P75, _utc(2026, 7, 13, 0)): 9.0,
        }
        windows = build_precip_windows(half_windows, pop_by_window_end, values)
        assert len(windows) == 2
        assert windows[0]["pop"] == 60
        assert windows[0]["amount_p25"] == 4.0
        assert windows[1]["pop"] == 10
        assert windows[1]["amount_p25"] is None


# ---------------------------------------------------------------------------
# Coordinator integration — _fetch_geps_day
# ---------------------------------------------------------------------------

def _mock_execute(captured: list, pop_value):
    """Return a mock _execute_queries that answers each GEPS layer synthetically."""
    layer_values = {
        GEPS_POP_12H: pop_value,
        GEPS_AMOUNT_P25: 3.0,
        GEPS_AMOUNT_P75: 8.0,
        GEPS_TEMPERATURE_P50: 20.0,
        GEPS_HUMIDEX_P50: 26.0,
        GEPS_CLOUD_P50: 70.0,
        GEPS_RAIN_MEDIAN: 4.0,
        GEPS_SNOW_MEDIAN: 0.0,
    }

    async def _execute(queries, now_ts, session, semaphore):
        captured.extend(queries)
        results = [
            (layer, ts, key, layer_values.get(layer))
            for layer, ts, key in queries
        ]
        return results, 0, len(results)

    return _execute


class TestFetchGepsDay:
    async def test_wet_day_synthesizes_timesteps_and_windows(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        captured: list = []
        coord._execute_queries = _mock_execute(captured, pop_value=60)

        entries, windows = await coord._fetch_geps_day(
            "2026-07-12", DAY5_PERIODS, TODAY, 0.0, None, None,
        )

        # Eight 3h steps (4 day + 4 night), all synthesized GEPS.
        assert len(entries) == 8
        assert all(e.model == "geps" for e in entries)
        assert all(e.temp == 20.0 for e in entries)
        assert all(e.pop == 60 for e in entries)
        assert all(e.icon_code == RAIN for e in entries)  # wet, rain-dominant

        # Wet windows trigger amount-band + precip-type queries.
        captured_layers = {layer for layer, _, _ in captured}
        assert GEPS_AMOUNT_P25 in captured_layers
        assert GEPS_RAIN_MEDIAN in captured_layers

        assert len(windows) == 2
        assert all(w["pop"] == 60 for w in windows)
        assert all(w["amount_p25"] == 3.0 and w["amount_p75"] == 8.0 for w in windows)

    async def test_dry_day_skips_wet_gated_queries(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        captured: list = []
        coord._execute_queries = _mock_execute(captured, pop_value=10)

        entries, windows = await coord._fetch_geps_day(
            "2026-07-12", DAY5_PERIODS, TODAY, 0.0, None, None,
        )

        assert all(e.pop == 10 for e in entries)
        # Dry -> NT cloud bucket (day/night variant per step's hour).
        assert all(e.icon_code in _MOSTLY_CLOUDY for e in entries)

        # POP below the wet gate -> no amount-band or precip-type queries.
        captured_layers = {layer for layer, _, _ in captured}
        assert GEPS_AMOUNT_P25 not in captured_layers
        assert GEPS_RAIN_MEDIAN not in captured_layers
        assert GEPS_SNOW_MEDIAN not in captured_layers

        assert [w["amount_p25"] for w in windows] == [None, None]

    async def test_non_geps_day_returns_empty(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        captured: list = []
        coord._execute_queries = _mock_execute(captured, pop_value=60)

        # Day 2 (2026-07-09) is HRDPS/RDPS, not GEPS.
        entries, windows = await coord._fetch_geps_day(
            "2026-07-09", DAY5_PERIODS, TODAY, 0.0, None, None,
        )
        assert entries == []
        assert windows is None
        assert captured == []  # no GEPS queries issued


# ---------------------------------------------------------------------------
# Coordinator integration — cache TTL, WEonG skip, projection
# ---------------------------------------------------------------------------

class TestGepsCacheTtl:
    def test_geps_layer_uses_geps_ttl(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        assert coord._cache_ttl(GEPS_POP_12H) == CACHE_TTL_GEPS
        assert coord._cache_ttl(GEPS_TEMPERATURE_P50) == CACHE_TTL_GEPS


class TestWeongPathSkipsGeps:
    @freeze_time("2026-07-07T12:00:00Z")
    def test_build_timestep_info_never_yields_geps(self, hass: HomeAssistant):
        """The WEonG timestep builder must never emit a geps model — the GEPS
        wave owns those (different layers, 3h grid, day-6 horizon)."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        from ec_weather.coordinator.weong_helpers import build_periods
        from homeassistant.util import dt as dt_util

        today = date(2026, 7, 7)
        now_utc = _utc(2026, 7, 7, 12)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)
        periods = build_periods(today, now_utc, local_tz)

        timestep_info = coord._build_timestep_info(periods, today)
        assert all(model != "geps" for _ts, _pk, model in timestep_info)


class TestPrecipWindowsProjection:
    def test_project_output_surfaces_precip_windows_in_range(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        band = [{"start": "2026-07-12T12:00:00Z", "end": "2026-07-13T00:00:00Z",
                 "pop": 60, "amount_p25": 3.0, "amount_p75": 8.0}]
        coord._precip_windows = {
            "2026-07-12": band,
            "2026-07-30": [{"pop": 10}],  # out of range -> filtered
        }
        output = coord._project_output(DAY5_PERIODS)
        assert output["precip_windows"] == {"2026-07-12": band}


# ---------------------------------------------------------------------------
# Coordinator integration — on-demand GEPS fetch
# ---------------------------------------------------------------------------

class TestOnDemandGepsFetch:
    @freeze_time("2026-07-07T12:00:00Z")
    async def test_fetch_day_timesteps_triggers_geps_for_geps_day(
        self, hass: HomeAssistant,
    ):
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        coord.data = {"periods": {}, "hourly": {}}
        captured: list = []
        coord._execute_queries = _mock_execute(captured, pop_value=60)

        from unittest.mock import AsyncMock, MagicMock, patch

        def mock_build_periods(today, now, local_tz):
            return list(DAY5_PERIODS)

        with patch(
            "ec_weather.coordinator.weong.build_periods",
            side_effect=mock_build_periods,
        ):
            await coord.async_fetch_day_timesteps("2026-07-12")

        # GEPS timesteps landed in the canonical store...
        geps_entries = [
            coord._store.get(key) for key in (
                "2026-07-12T12:00:00Z", "2026-07-13T00:00:00Z",
            )
        ]
        assert all(e is not None and e.model == "geps" for e in geps_entries)

        # ...the day is marked fetched, and precip_windows are published.
        assert "2026-07-12" in coord.data["days_fetched"]
        assert "2026-07-12" in coord.data["precip_windows"]


# ---------------------------------------------------------------------------
# Contract guard — the official 7 daily entries keep their exact key set
# ---------------------------------------------------------------------------

def _daily_stub(date_str: str) -> dict:
    return {
        "period": date_str,
        "date": date_str,
        "temp_high": 24,
        "temp_low": 13,
        "icon_code": 12,
        "condition_day": "Rain",
        "condition_night": "Cloudy",
    }


class TestDailyForecastContractGuard:
    def test_first_seven_entries_only_add_precip_windows_on_geps_days(self):
        """Automations/widgets read the daily-forecast attribute — the first 7
        entries must keep every existing key. The GEPS band is the ONLY additive
        key, and only on geps days (4-6)."""
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]  # days 0-6
        daily = [_daily_stub(d) for d in dates]
        geps_dates = dates[4:]  # days 4, 5, 6

        precip_windows = {
            d: [{"start": f"{d}T12:00:00Z", "end": f"{d}T18:00:00Z",
                 "pop": 55, "amount_p25": 3.0, "amount_p75": 8.0}]
            for d in geps_dates
        }
        days_fetched = list(dates)

        baseline = merge_weong_into_daily(
            daily, {}, days_fetched=days_fetched,
        )
        with_bands = merge_weong_into_daily(
            daily, {}, days_fetched=days_fetched, precip_windows=precip_windows,
        )

        assert len(baseline) == len(with_bands) == 7
        for offset, (base, band) in enumerate(zip(baseline, with_bands)):
            base_keys = set(base)
            band_keys = set(band)
            # Baseline never carries the additive key.
            assert "precip_windows" not in base_keys
            if offset >= 4:
                # Geps day: exactly the additive key is added, nothing removed.
                assert band_keys == base_keys | {"precip_windows"}
                assert band["precip_windows"] == precip_windows[dates[offset]]
            else:
                # Official near days: byte-for-byte identical key set.
                assert band_keys == base_keys
                assert "precip_windows" not in band_keys


# ---------------------------------------------------------------------------
# Phase C — outlook coverage + scheduling helpers
# ---------------------------------------------------------------------------

class TestOutlookCoverage:
    def test_outlook_days_ahead_by_mode(self):
        assert outlook_days_ahead(7) == []            # default: no outlook
        assert outlook_days_ahead(10) == [7, 8, 9]    # + days 8-10 (1-indexed)
        assert outlook_days_ahead(14) == [7, 8, 9, 10, 11, 12, 13]

    def test_is_outlook_day_gated_by_forecast_days(self):
        assert not is_outlook_day(6, 10)   # last official day
        assert is_outlook_day(7, 10)
        assert is_outlook_day(9, 10)
        assert not is_outlook_day(10, 10)  # beyond mode-10 scope
        assert is_outlook_day(10, 14)
        assert not is_outlook_day(7, 7)    # mode 7 has no outlook

    def test_outlook_dates_are_beyond_the_official_seven(self):
        # TODAY is 2026-07-07 (day 0); the official list ends at 2026-07-13.
        assert outlook_dates(TODAY, 10) == ["2026-07-14", "2026-07-15", "2026-07-16"]
        assert outlook_dates(TODAY, 7) == []


class TestNearestGepsStep:
    @pytest.mark.parametrize(
        "moment,expected",
        [
            (_utc(2026, 7, 16, 18), _utc(2026, 7, 16, 18)),  # on grid -> unchanged
            (_utc(2026, 7, 16, 19), _utc(2026, 7, 16, 18)),  # 19 -> 18 (nearest)
            (_utc(2026, 7, 16, 20), _utc(2026, 7, 16, 21)),  # 20 -> 21 (nearest)
            (_utc(2026, 7, 16, 13), _utc(2026, 7, 16, 12)),  # 13 -> 12
            (_utc(2026, 7, 16, 14), _utc(2026, 7, 16, 15)),  # 14 -> 15
            (_utc(2026, 7, 16, 22, 40), _utc(2026, 7, 16, 23, 40)),  # nearest hour first? no
        ],
    )
    def test_rounds_to_nearest_three_hour_grid(self, moment, expected):
        # The last case is a sanity check that sub-hour minutes carry through:
        # 22:40 rounds to nearest hour 23, which is not on the 3h grid -> 24 (00Z).
        if moment == _utc(2026, 7, 16, 22, 40):
            assert nearest_geps_step(moment) == _utc(2026, 7, 17, 0)
        else:
            assert nearest_geps_step(moment) == expected


class TestOutlookSamplePoints:
    def test_rep_steps_and_windows_for_a_summer_day(self):
        points = outlook_sample_points("2026-07-16", ET)
        # Day peak ~15:00 EDT (19:00Z) -> nearest 3h grid 18:00Z, inside the
        # 12Z-00Z day window. Night trough ~05:00 EDT next day (09:00Z) -> 09:00Z,
        # inside the 00Z-12Z morning window.
        assert points["day_rep"] == _utc(2026, 7, 16, 18)
        assert points["night_rep"] == _utc(2026, 7, 17, 9)
        assert points["day_window_end"] == _utc(2026, 7, 17, 0)
        assert points["night_window_end"] == _utc(2026, 7, 17, 12)


# ---------------------------------------------------------------------------
# Phase C — outlook query plan + fold
# ---------------------------------------------------------------------------

class TestPlanOutlookBaseQueries:
    def test_day_and_night_rep_layers(self):
        day_rep = _utc(2026, 7, 16, 18)
        night_rep = _utc(2026, 7, 17, 9)
        queries = plan_outlook_base_queries(day_rep, night_rep)
        day_layers = {layer for layer, ts, _ in queries if ts == day_rep}
        night_layers = {layer for layer, ts, _ in queries if ts == night_rep}
        # Day rep carries the p75 band (warm side); night rep the p25 band.
        assert day_layers == {
            GEPS_TEMPERATURE_P50, GEPS_TEMPERATURE_P75,
            GEPS_HUMIDEX_P50, GEPS_CLOUD_P50,
        }
        assert night_layers == {
            GEPS_TEMPERATURE_P50, GEPS_TEMPERATURE_P25,
            GEPS_HUMIDEX_P50, GEPS_CLOUD_P50,
        }
        assert all(key == GEPS_QUERY_TAG for _, _, key in queries)


_OUTLOOK_POINTS = {
    "day_rep": _utc(2026, 7, 16, 18),
    "night_rep": _utc(2026, 7, 17, 9),
    "day_window_end": _utc(2026, 7, 17, 0),
    "night_window_end": _utc(2026, 7, 17, 12),
}


def _outlook_values():
    day_rep = _OUTLOOK_POINTS["day_rep"]
    night_rep = _OUTLOOK_POINTS["night_rep"]
    day_we = _OUTLOOK_POINTS["day_window_end"]
    return {
        (GEPS_TEMPERATURE_P50, day_rep): 24.0,
        (GEPS_TEMPERATURE_P75, day_rep): 27.0,
        (GEPS_HUMIDEX_P50, day_rep): 28.0,
        (GEPS_CLOUD_P50, day_rep): 70.0,
        (GEPS_TEMPERATURE_P50, night_rep): 13.0,
        (GEPS_TEMPERATURE_P25, night_rep): 11.0,
        (GEPS_HUMIDEX_P50, night_rep): 15.0,
        (GEPS_CLOUD_P50, night_rep): 30.0,
        # Wet day window (POP 55 >= gate): amount band + precip-type medians.
        (GEPS_AMOUNT_P25, day_we): 4.0,
        (GEPS_AMOUNT_P75, day_we): 9.0,
        (GEPS_RAIN_MEDIAN, day_we): 5.0,
        (GEPS_SNOW_MEDIAN, day_we): 0.0,
    }


class TestBuildOutlookEntry:
    def _entry(self):
        pop_by_window_end = {
            _OUTLOOK_POINTS["day_window_end"]: 55,
            _OUTLOOK_POINTS["night_window_end"]: 20,
        }
        return build_outlook_entry(
            "2026-07-16", _OUTLOOK_POINTS, pop_by_window_end, _outlook_values(),
        )

    def test_median_scalars_and_band(self):
        entry = self._entry()
        assert entry["temp_high"] == 24.0
        assert entry["temp_low"] == 13.0
        assert entry["temp_range"] == {"low": 11.0, "high": 27.0}

    def test_source_and_period(self):
        entry = self._entry()
        assert entry["source"] == "outlook"
        assert entry["date"] == "2026-07-16"
        assert entry["period"] == "2026-07-16"

    def test_pop_and_icons_per_half(self):
        entry = self._entry()
        assert entry["pop_day"] == 55
        assert entry["pop_night"] == 20
        assert entry["pop_day_display"] == 55
        assert entry["pop_night_display"] is None
        # Day: pop 55 (chance band) rain-dominant -> chance of showers.
        # Night: pop 20 (dry) cloud 30% -> partly cloudy night.
        assert entry["icon_day"] == _CHANCE_OF_SHOWERS
        assert entry["icon_night"] == PARTLY_CLOUDY_NIGHT

    def test_amount_band_and_feels_like(self):
        entry = self._entry()
        assert entry["amount_band"] == {"low": 4.0, "high": 9.0}
        assert entry["feels_like_day"] == 28.0     # temp 24 >= 20, humidex 28
        assert entry["feels_like_night"] is None    # temp 13 < 20 -> gated off

    def test_sentence_params_present(self):
        entry = self._entry()
        assert entry["sentence"] == {
            "range_low": 11,
            "range_high": 27,
            "dominant_pop": 55,
            "amount_band": {"low": 4.0, "high": 9.0},
        }

    def test_no_timesteps_keys_and_outlook_state(self):
        entry = self._entry()
        # Outlook days have no timeline at all — the honest representation is
        # an explicit state plus the absence of any timestep lists.
        assert entry["timesteps_state"] == "outlook"
        assert "timesteps_day" not in entry
        assert "timesteps_night" not in entry

    def test_no_dishonest_scalar_keys(self):
        entry = self._entry()
        for forbidden in (
            "humidity", "wind_speed", "wind_gust", "wind_direction",
            "condition", "text_summary",
        ):
            assert forbidden not in entry

    def test_dry_day_has_no_amount_band(self):
        pop_by_window_end = {
            _OUTLOOK_POINTS["day_window_end"]: 20,
            _OUTLOOK_POINTS["night_window_end"]: 10,
        }
        entry = build_outlook_entry(
            "2026-07-16", _OUTLOOK_POINTS, pop_by_window_end, _outlook_values(),
        )
        assert entry["amount_band"] is None


# ---------------------------------------------------------------------------
# Phase C — coordinator outlook fetch + projection
# ---------------------------------------------------------------------------

def _mock_outlook_execute(captured: list):
    """Mock _execute_queries answering every outlook GEPS layer synthetically."""
    layer_values = {
        GEPS_POP_12H: 55,
        GEPS_TEMPERATURE_P25: 11.0,
        GEPS_TEMPERATURE_P50: 20.0,
        GEPS_TEMPERATURE_P75: 27.0,
        GEPS_HUMIDEX_P50: 26.0,
        GEPS_CLOUD_P50: 70.0,
        GEPS_AMOUNT_P25: 4.0,
        GEPS_AMOUNT_P75: 9.0,
        GEPS_RAIN_MEDIAN: 5.0,
        GEPS_SNOW_MEDIAN: 0.0,
    }

    async def _execute(queries, now_ts, session, semaphore):
        captured.extend(queries)
        results = [
            (layer, ts, key, layer_values.get(layer))
            for layer, ts, key in queries
        ]
        return results, 0, len(results)

    return _execute


class TestCoordinatorFetchOutlook:
    async def test_forecast_days_seven_fetches_no_outlook(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])
        captured: list = []
        coord._execute_queries = _mock_outlook_execute(captured)

        await coord._fetch_outlook(TODAY, 0.0, None, None, ET)

        assert coord._outlook == {}
        assert captured == []  # no GEPS queries at all in mode 7

    async def test_legacy_intermediate_value_tolerated(self, hass: HomeAssistant):
        # "10" was removed from the selector (no confidence boundary behind it
        # after the single-source GEPS decision) but a stored legacy value must
        # keep working: outlook_days_ahead is generic over the int.
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=10,
        )
        captured: list = []
        coord._execute_queries = _mock_outlook_execute(captured)

        await coord._fetch_outlook(TODAY, 0.0, None, None, ET)

        assert sorted(coord._outlook) == ["2026-07-14", "2026-07-15", "2026-07-16"]
        entry = coord._outlook["2026-07-16"]
        assert entry["source"] == "outlook"
        assert entry["timesteps_state"] == "outlook"
        assert "sentence" in entry
        assert "timesteps_day" not in entry


class TestOutlookProjection:
    @freeze_time("2026-07-07T12:00:00Z")
    def test_project_output_surfaces_sorted_outlook(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=10,
        )
        # All three outlook dates have real entries -> no skeletons; the
        # projection just sorts them by date.
        coord._outlook = {
            "2026-07-16": {"date": "2026-07-16", "source": "outlook"},
            "2026-07-14": {"date": "2026-07-14", "source": "outlook"},
            "2026-07-15": {"date": "2026-07-15", "source": "outlook"},
        }
        output = coord._project_output(DAY5_PERIODS)
        assert [e["date"] for e in output["outlook"]] == [
            "2026-07-14", "2026-07-15", "2026-07-16",
        ]

    def test_project_output_outlook_empty_by_default(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])
        output = coord._project_output(DAY5_PERIODS)
        assert output["outlook"] == []


# ---------------------------------------------------------------------------
# Refinement 1 — skeleton outlook rows on enable
# ---------------------------------------------------------------------------

class TestOutlookSkeletons:
    """When extended is enabled, the projection emits SKELETON outlook entries
    for dates not yet in the store, so the daily attribute shows the full
    expected date range immediately after the reload that follows enabling."""

    @freeze_time("2026-07-07T12:00:00Z")
    def test_emits_skeletons_only_for_missing_dates(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=10,
        )
        # No outlook data fetched yet -> every outlook date is a skeleton.
        output = coord._project_output(DAY5_PERIODS)
        entries = output["outlook"]
        assert [e["date"] for e in entries] == [
            "2026-07-14", "2026-07-15", "2026-07-16",
        ]
        for entry in entries:
            assert entry["source"] == "outlook"
            assert entry["pending"] is True
            # Skeletons carry NO temps / icons / sentence.
            assert "temp_low" not in entry
            assert "temp_high" not in entry
            assert "icon_day" not in entry
            assert "sentence" not in entry

    @freeze_time("2026-07-07T12:00:00Z")
    def test_real_entries_replace_skeletons(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=10,
        )
        # One real entry landed; the other two dates stay skeletons.
        coord._outlook = {
            "2026-07-15": {
                "date": "2026-07-15", "source": "outlook",
                "temp_low": 12, "temp_high": 22,
            },
        }
        entries = {e["date"]: e for e in coord._project_output(DAY5_PERIODS)["outlook"]}
        assert entries["2026-07-15"].get("pending") is None
        assert entries["2026-07-15"]["temp_low"] == 12
        assert entries["2026-07-14"]["pending"] is True
        assert entries["2026-07-16"]["pending"] is True

    @freeze_time("2026-07-07T12:00:00Z")
    def test_no_skeletons_when_extended_off(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])
        assert coord._project_output(DAY5_PERIODS)["outlook"] == []

    def test_skeleton_outlook_appended_after_official_seven(self):
        """Skeleton entries flow through the merge as outlook rows: appended
        after the official 7, leaving the contract-guarded entries untouched."""
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]
        skeletons = [
            {"date": "2026-07-14", "source": "outlook", "pending": True},
            {"date": "2026-07-15", "source": "outlook", "pending": True},
        ]

        baseline = merge_weong_into_daily(daily, {})
        merged = merge_weong_into_daily(daily, {}, outlook=skeletons)

        assert merged[:7] == baseline
        assert [e.get("pending") for e in merged[7:]] == [True, True]
        assert [e["source"] for e in merged[7:]] == ["outlook", "outlook"]


# ---------------------------------------------------------------------------
# Refinement 2 — day-7 (last official day) overnight-low backfill
# ---------------------------------------------------------------------------

class TestDay7NightBackfill:
    """When extended is enabled and EC's last official day lacks its overnight
    low, the outlook wave backfills it from the GEPS night trough."""

    async def test_disabled_when_extended_off(self, hass: HomeAssistant):
        coord = _make_coord(hass)  # forecast_days=7
        captured: list = []
        coord._execute_queries = _mock_outlook_execute(captured)

        await coord._fetch_day7_backfill(TODAY, 0.0, None, None, ET)

        assert coord._day7_backfill is None
        assert captured == []  # no GEPS queries when off

    async def test_samples_night_trough_of_last_official_day(self, hass: HomeAssistant):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=10,
        )
        captured: list = []
        coord._execute_queries = _mock_outlook_execute(captured)

        await coord._fetch_day7_backfill(TODAY, 0.0, None, None, ET)

        # Last official day is TODAY + 6.
        last_official = "2026-07-13"
        points = outlook_sample_points(last_official, ET)
        backfill = coord._day7_backfill
        assert backfill["date"] == last_official
        # TT p50 (20.0) rounded to the whole-degree convention of official lows.
        assert backfill["temp_low"] == 20
        assert backfill["pop_night"] == 55  # ERGE1 at the covering 12h window

        # Budget: exactly the two backfill queries (TT p50 + POP), at the
        # night trough and its covering window.
        assert len(captured) == 2
        layers = {layer for layer, _, _ in captured}
        assert layers == {GEPS_TEMPERATURE_P50, GEPS_POP_12H}
        query_by_layer = {layer: ts for layer, ts, _ in captured}
        assert query_by_layer[GEPS_TEMPERATURE_P50] == points["night_rep"]
        assert query_by_layer[GEPS_POP_12H] == points["night_window_end"]


class TestMergeBackfillLastOfficialDay:
    """merge_weong_into_daily fills the last official day's absent overnight low
    (and night POP) from the outlook backfill, never overwriting published EC
    values, and only when extended supplies the payload."""

    def _daily_last_day_missing_low(self):
        # Seven official days; the last (offset 6) has no published night.
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]
        last = daily[-1]
        last["temp_low"] = None
        return daily

    def test_fills_absent_low_and_night_pop(self):
        daily = self._daily_last_day_missing_low()
        backfill = {"date": "2026-07-13", "temp_low": 11, "pop_night": 40}
        merged = merge_weong_into_daily(daily, {}, outlook_backfill=backfill)
        assert merged[-1]["temp_low"] == 11
        assert merged[-1]["precip_prob_night"] == 40

    def test_never_overwrites_published_low(self):
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]  # last day has temp_low=13
        backfill = {"date": "2026-07-13", "temp_low": 11, "pop_night": 40}
        merged = merge_weong_into_daily(daily, {}, outlook_backfill=backfill)
        assert merged[-1]["temp_low"] == 13  # published value untouched

    def test_never_overwrites_published_night_pop(self):
        # A fully published last day (low + WEonG night POP present): the
        # backfill must leave BOTH intact — it only fills absent halves.
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]  # last day has temp_low=13
        weong_periods = {("2026-07-13", "night"): {"pop": 70}}
        backfill = {"date": "2026-07-13", "temp_low": 11, "pop_night": 40}
        merged = merge_weong_into_daily(
            daily, weong_periods, outlook_backfill=backfill,
        )
        assert merged[-1]["temp_low"] == 13          # published low untouched
        assert merged[-1]["precip_prob_night"] == 70  # WEonG night POP wins

    def test_only_matching_date_is_filled(self):
        daily = self._daily_last_day_missing_low()
        backfill = {"date": "2026-07-99", "temp_low": 11, "pop_night": 40}
        merged = merge_weong_into_daily(daily, {}, outlook_backfill=backfill)
        assert merged[-1]["temp_low"] is None  # no matching date -> untouched

    def test_no_backfill_param_leaves_forecast_unchanged(self):
        daily = self._daily_last_day_missing_low()
        merged = merge_weong_into_daily(daily, {})
        assert merged[-1]["temp_low"] is None


# ---------------------------------------------------------------------------
# Phase C — daily-forecast append + weather-entity isolation
# ---------------------------------------------------------------------------

class TestDailyForecastOutlookAppend:
    def test_outlook_appended_after_the_official_seven(self):
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]
        outlook = [
            {"date": "2026-07-14", "period": "2026-07-14", "source": "outlook",
             "temp_high": 22, "temp_low": 12, "timesteps_state": "outlook"},
            {"date": "2026-07-15", "period": "2026-07-15", "source": "outlook",
             "temp_high": 23, "temp_low": 13, "timesteps_state": "outlook"},
        ]

        baseline = merge_weong_into_daily(daily, {})
        merged = merge_weong_into_daily(daily, {}, outlook=outlook)

        # Official 7 untouched, outlook appended after them.
        assert len(baseline) == 7
        assert len(merged) == 9
        assert merged[:7] == baseline
        assert [e["source"] for e in merged[7:]] == ["outlook", "outlook"]
        assert [e["date"] for e in merged[7:]] == ["2026-07-14", "2026-07-15"]

    def test_no_outlook_keeps_seven(self):
        dates = [f"2026-07-{7 + offset:02d}" for offset in range(7)]
        daily = [_daily_stub(d) for d in dates]
        assert len(merge_weong_into_daily(daily, {}, outlook=None)) == 7
        assert len(merge_weong_into_daily(daily, {}, outlook=[])) == 7


class TestWeatherEntityOutlookIsolation:
    def test_weather_daily_forecast_never_passes_outlook(self):
        """The HA weather entity must keep serving exactly the official days —
        outlook rows are a card-only concern, so async_forecast_daily must not
        forward the WEonG coordinator's outlook into its forecast."""
        import inspect

        from ec_weather.weather import ECWeather

        source = inspect.getsource(ECWeather.async_forecast_daily)
        assert "outlook" not in source, (
            "async_forecast_daily must not include outlook entries — the HA "
            "weather forecast stays official-only (days beyond EC's 7 are "
            "rendered by the card, not the weather entity)."
        )


class TestApplyForecastDays:
    """apply_forecast_days publishes skeletons instantly, no reload."""

    def test_publishes_skeletons_and_schedules_refresh(self, hass):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=7,
        )
        published = []
        coord.async_set_updated_data = lambda data: published.append(data)
        coord.async_request_refresh = AsyncMock()
        hass.async_create_task = MagicMock()

        coord.apply_forecast_days(14)

        assert coord._forecast_days == 14
        assert published, "projection must publish immediately"
        outlook = published[-1]["outlook"]
        assert outlook and all(e.get("pending") for e in outlook)
        hass.async_create_task.assert_called_once()

    def test_same_value_is_a_noop(self, hass):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=7,
        )
        published = []
        coord.async_set_updated_data = lambda data: published.append(data)
        hass.async_create_task = MagicMock()

        coord.apply_forecast_days(7)

        assert published == []
        hass.async_create_task.assert_not_called()

    def test_turning_off_drops_outlook(self, hass):
        coord = ECWEonGCoordinator(
            hass, MOCK_CONFIG_DATA["geomet_bbox"], forecast_days=14,
        )
        coord._outlook = {"2026-07-16": {"date": "2026-07-16"}}
        coord.async_set_updated_data = lambda data: None
        hass.async_create_task = MagicMock()

        coord.apply_forecast_days(7)

        assert coord._outlook == {}
