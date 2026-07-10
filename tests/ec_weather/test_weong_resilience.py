"""Resilience hardening for the WEonG GeoMet wave (degraded-API handling).

Covers the four fixes made after a GeoMet degradation episode cached failure
holes with the normal TTL:

  F1 — never cache failures (transient error / 429 / unparseable body).
  F2 — a partial day is not marked done; the 15-min retry refetches it.
  F3 — a half-built outlook row keeps its pending skeleton (tested in
       test_extended.py alongside the other outlook cases).
  F4 — honor 429 with a two-step backoff and pace the cold start in chunks.

All failure modes are simulated; every value is synthetic (repo policy).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.const import (
    WEONG_BACKOFF_FIRST_SECONDS,
    WEONG_BACKOFF_SECOND_SECONDS,
    WEONG_CHUNK_DELAY_SECONDS,
    WEONG_DAY_COMPLETE_MIN_RATIO,
    WEONG_SEMAPHORE_LIMIT,
)
from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.weong_helpers import _LAYER_SUFFIXES, _weong_layer_name

from .conftest import MOCK_CONFIG_DATA


def _make_coord(hass: HomeAssistant) -> ECWEonGCoordinator:
    return ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# F1 — failures are never cached
# ---------------------------------------------------------------------------

class TestRateLimitNotCached:
    async def test_rate_limited_sentinel_not_cached(self, hass: HomeAssistant):
        """A 429 (RATE_LIMITED sentinel) must never enter the layer cache."""
        coord = _make_coord(hass)
        now_ts = datetime.now(timezone.utc).timestamp()
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)
        ts = _utc(2026, 3, 25, 12)
        layer = "RDPS-WEonG_10km_Precip-Prob"

        async def mock_query(session, layer, timestep):
            return coord._RATE_LIMITED

        coord._query_feature_info = mock_query

        with patch("asyncio.sleep", return_value=None):
            results, _cached, _fetched = await coord._execute_queries(
                [(layer, ts, ("2026-03-25", "day"))], now_ts, None, semaphore,
            )

        assert results[0][3] is None  # treated as no-data for aggregation
        assert (layer, ts.strftime("%Y-%m-%dT%H:%M:%SZ")) not in coord._cache
        assert coord._had_transient_errors is True


# ---------------------------------------------------------------------------
# F2 — a partial day is not marked done
# ---------------------------------------------------------------------------

def _base_results(timesteps, values, model="hrdps"):
    """Build POP+AirTemp base results, one of each per timestep.

    ``values`` is a list of the POP value per timestep; None simulates a failed
    (timed-out, never-cached) query. AirTemp mirrors POP presence so the
    completeness ratio is driven by how many base queries returned a value.
    """
    pop_layer = _weong_layer_name(_LAYER_SUFFIXES["precip_prob"], model)
    temp_layer = _weong_layer_name(_LAYER_SUFFIXES["air_temp"], model)
    out = []
    for ts, value in zip(timesteps, values):
        out.append((pop_layer, ts, ("2026-03-25", "day"), value))
        temp = None if value is None else -5.0
        out.append((temp_layer, ts, ("2026-03-25", "day"), temp))
    return out


class TestPartialDayCompleteness:
    def test_threshold_constant_is_named_and_sixty_percent(self):
        assert WEONG_DAY_COMPLETE_MIN_RATIO == 0.6

    def test_full_day_is_complete(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        timesteps = [_utc(2026, 3, 25, 12 + i) for i in range(10)]
        results = _base_results(timesteps, [10.0] * 10)
        succeeded, total = coord._weong_base_completeness(results)
        assert (succeeded, total) == (20, 20)
        assert coord._is_day_complete(succeeded, total, geps_entries=[]) is True

    def test_below_threshold_is_incomplete(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        timesteps = [_utc(2026, 3, 25, 12 + i) for i in range(10)]
        # Only 3 of 10 timesteps answered (3/24-style hole): 6 of 20 base = 30%.
        values = [10.0, 20.0, 30.0] + [None] * 7
        results = _base_results(timesteps, values)
        succeeded, total = coord._weong_base_completeness(results)
        assert coord._is_day_complete(succeeded, total, geps_entries=[]) is False

    def test_no_base_queries_is_complete(self, hass: HomeAssistant):
        """Past the 84h horizon a day has no base queries at all — that empty
        answer is legitimate and must count as complete (not a perpetual retry).
        """
        coord = _make_coord(hass)
        assert coord._is_day_complete(0, 0, geps_entries=[]) is True

    async def test_process_day_skips_completed_on_partial(self, hass: HomeAssistant):
        """A partial background day must NOT enter _completed_days, so it keeps
        its pending state and the retry machinery refetches it."""
        from datetime import date

        coord = _make_coord(hass)
        date_str = "2026-03-25"
        day_periods = [
            (date_str, "day", _utc(2026, 3, 25, 10), _utc(2026, 3, 25, 22)),
        ]
        today = date(2026, 3, 25)

        # 2 of 12 timesteps answered -> well below 60%.
        async def mock_fetch_day(dp, td, now_ts, session, sem):
            steps = [_utc(2026, 3, 25, 10 + i) for i in range(12)]
            values = [10.0, 20.0] + [None] * 10
            return _base_results(steps, values)

        async def mock_geps(date_str, dp, td, now_ts, session, sem):
            return [], None

        coord._fetch_day = mock_fetch_day
        coord._fetch_geps_day = mock_geps

        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)
        await coord._process_day(
            date_str, day_periods, today, 0.0, None, semaphore, day_periods,
        )

        assert date_str not in coord._completed_days
        assert coord._had_incomplete_days is True

    async def test_process_day_marks_complete_when_healthy(self, hass: HomeAssistant):
        from datetime import date

        coord = _make_coord(hass)
        date_str = "2026-03-25"
        day_periods = [
            (date_str, "day", _utc(2026, 3, 25, 10), _utc(2026, 3, 25, 22)),
        ]
        today = date(2026, 3, 25)

        async def mock_fetch_day(dp, td, now_ts, session, sem):
            steps = [_utc(2026, 3, 25, 10 + i) for i in range(12)]
            return _base_results(steps, [10.0] * 12)

        async def mock_geps(date_str, dp, td, now_ts, session, sem):
            return [], None

        coord._fetch_day = mock_fetch_day
        coord._fetch_geps_day = mock_geps

        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)
        await coord._process_day(
            date_str, day_periods, today, 0.0, None, semaphore, day_periods,
        )

        assert date_str in coord._completed_days


class TestOnDemandPartialNotCached:
    async def test_failed_ondemand_fetch_not_cached(self, hass: HomeAssistant):
        """An on-demand SkyState fetch that mostly failed must NOT cache a done
        marker or mark the day complete — a re-open must re-ask EC (F1 + F2)."""
        from datetime import datetime as _dt

        coord = _make_coord(hass)
        coord.data = {"periods": {}, "hourly": {}}
        date_str = "2026-03-23"

        def mock_build_periods(today, now, local_tz):
            return [
                (date_str, "day",
                 _utc(2026, 3, 23, 10), _utc(2026, 3, 23, 22)),
            ]

        # SkyState fetch: only 2 of many timesteps answered (rest None).
        async def mock_execute(queries, now_ts, session, semaphore):
            results = []
            for i, (layer, ts, pk) in enumerate(queries):
                results.append((layer, ts, pk, 3.0 if i < 2 else None))
            return results, 0, len(results)

        coord._execute_queries = mock_execute

        with patch("ec_weather.coordinator.weong.build_periods",
                   side_effect=mock_build_periods):
            await coord.async_fetch_day_timesteps(date_str)

        assert date_str not in coord._timestep_cache
        assert date_str not in coord._completed_days

    async def test_healthy_ondemand_fetch_is_cached(self, hass: HomeAssistant):
        coord = _make_coord(hass)
        coord.data = {"periods": {}, "hourly": {}}
        date_str = "2026-03-23"

        def mock_build_periods(today, now, local_tz):
            return [
                (date_str, "day",
                 _utc(2026, 3, 23, 10), _utc(2026, 3, 23, 22)),
            ]

        async def mock_execute(queries, now_ts, session, semaphore):
            return [(l, ts, pk, 3.0) for l, ts, pk in queries], 0, len(queries)

        coord._execute_queries = mock_execute

        with patch("ec_weather.coordinator.weong.build_periods",
                   side_effect=mock_build_periods):
            await coord.async_fetch_day_timesteps(date_str)

        assert date_str in coord._timestep_cache
        assert date_str in coord._completed_days


# ---------------------------------------------------------------------------
# F4 — honor 429 and pace the cold start
# ---------------------------------------------------------------------------

class TestRateLimitBackoff:
    async def test_first_429_pauses_short_then_second_longer(self, hass: HomeAssistant):
        """A first 429 pauses the short backoff, a second the long one."""
        coord = _make_coord(hass)
        now_ts = datetime.now(timezone.utc).timestamp()
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)
        layer = "RDPS-WEonG_10km_Precip-Prob"

        async def mock_query(session, layer, timestep):
            return coord._RATE_LIMITED

        coord._query_feature_info = mock_query

        slept: list[float] = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await coord._execute_queries(
                [(layer, _utc(2026, 3, 25, 12), ("2026-03-25", "day"))],
                now_ts, None, semaphore,
            )
            await coord._execute_queries(
                [(layer, _utc(2026, 3, 25, 13), ("2026-03-25", "day"))],
                now_ts, None, semaphore,
            )

        assert WEONG_BACKOFF_FIRST_SECONDS in slept
        assert WEONG_BACKOFF_SECOND_SECONDS in slept

    async def test_cold_start_paces_between_chunks(self, hass: HomeAssistant):
        """More than one semaphore-sized chunk inserts a pacing delay between
        chunks so a reboot does not spike hundreds of near-concurrent requests.
        """
        coord = _make_coord(hass)
        now_ts = datetime.now(timezone.utc).timestamp()
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)
        layer = "RDPS-WEonG_10km_Precip-Prob"

        async def mock_query(session, layer, timestep):
            return 5.0

        coord._query_feature_info = mock_query

        # Two-and-a-bit chunks worth of distinct queries.
        queries = [
            (layer, _utc(2026, 3, 25, 0) + timedelta(hours=i), ("2026-03-25", "day"))
            for i in range(WEONG_SEMAPHORE_LIMIT * 2 + 1)
        ]

        slept: list[float] = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await coord._execute_queries(queries, now_ts, None, semaphore)

        pacing = [s for s in slept if s == WEONG_CHUNK_DELAY_SECONDS]
        # 3 chunks -> 2 inter-chunk delays.
        assert len(pacing) == 2
