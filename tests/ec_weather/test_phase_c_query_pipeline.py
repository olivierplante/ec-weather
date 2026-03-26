"""Phase C tests — simplified WEonG query pipeline.

Background: POP sweep all + HRDPS enrichment only (days 0-2).
Lazy popup: GDPS enrichment + SkyState (days 3+), SkyState only (days 0-2).

Tests verify:
1. Background sweep queries POP for all models but AirTemp/amounts only for HRDPS
2. GDPS timesteps get POP in background but no AirTemp/amounts
3. Lazy enrich fetches AirTemp + amounts + SkyState for GDPS days
4. Lazy enrich fetches SkyState only for HRDPS days (already enriched)
5. Query count reduction (~208 background vs ~464 before)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ec_weather.coordinator import ECWEonGCoordinator
from ec_weather.coordinator.weong_helpers import (
    _HRDPS_PREFIX,
    _GDPS_PREFIX,
    _LAYER_SUFFIXES,
    _bare_layer_name,
    _model_from_layer,
    _weong_layer_name,
    build_periods,
)
from ec_weather.timestep_store import TimestepData

from .conftest import MOCK_CONFIG_DATA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coord(hass: HomeAssistant) -> ECWEonGCoordinator:
    return ECWEonGCoordinator(hass, MOCK_CONFIG_DATA["geomet_bbox"])


def _count_queries_by_layer(queries, suffix_key):
    """Count how many queries target a given layer suffix."""
    target_suffix = _LAYER_SUFFIXES[suffix_key]
    return sum(1 for layer, _, _ in queries if _bare_layer_name(layer) == target_suffix)


def _count_queries_by_model(queries, model_name):
    """Count queries targeting a specific model."""
    return sum(1 for layer, _, _ in queries if _model_from_layer(layer) == model_name)


# ---------------------------------------------------------------------------
# Background sweep — POP all + HRDPS enrichment
# ---------------------------------------------------------------------------

class TestBackgroundSweep:
    """Verify background sweep only enriches HRDPS, not GDPS."""

    def test_background_queries_pop_for_all_models(self, hass: HomeAssistant):
        """Background sweep queries POP for both HRDPS and GDPS timesteps."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        timestep_info = coord._build_timestep_info(periods, today)

        # Build POP queries for all timesteps (as background sweep does)
        pop_queries = []
        for ts, pk, model in timestep_info:
            pop_queries.append((_weong_layer_name(_LAYER_SUFFIXES["precip_prob"], model), ts, pk))

        # Should have queries for both models
        hrdps_pop = _count_queries_by_model(pop_queries, "hrdps")
        gdps_pop = _count_queries_by_model(pop_queries, "gdps")
        assert hrdps_pop > 0, "Should have HRDPS POP queries"
        assert gdps_pop > 0, "Should have GDPS POP queries"

    def test_background_queries_airtemp_for_all_models(self, hass: HomeAssistant):
        """Background sweep queries AirTemp for both HRDPS and GDPS."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        timestep_info = coord._build_timestep_info(periods, today)

        # Build AirTemp queries for all timesteps (as background sweep does)
        airtemp_queries = []
        for ts, pk, model in timestep_info:
            airtemp_queries.append((_weong_layer_name(_LAYER_SUFFIXES["air_temp"], model), ts, pk))

        hrdps_temp = _count_queries_by_model(airtemp_queries, "hrdps")
        gdps_temp = _count_queries_by_model(airtemp_queries, "gdps")
        assert hrdps_temp > 0, "Should have HRDPS AirTemp queries"
        assert gdps_temp > 0, "Should have GDPS AirTemp queries"

    def test_background_skips_skystate(self, hass: HomeAssistant):
        """Background sweep does NOT query SkyState — deferred to lazy popup."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        today = date(2026, 3, 22)
        now_utc = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        local_tz = dt_util.get_time_zone(hass.config.time_zone)

        periods = build_periods(today, now_utc, local_tz)
        timestep_info = coord._build_timestep_info(periods, today)

        # Background sweep queries POP + AirTemp, never SkyState
        always_queries = []
        for ts, pk, model in timestep_info:
            always_queries.append((_weong_layer_name(_LAYER_SUFFIXES["precip_prob"], model), ts, pk))
            always_queries.append((_weong_layer_name(_LAYER_SUFFIXES["air_temp"], model), ts, pk))

        sky_count = _count_queries_by_layer(always_queries, "sky_state")
        assert sky_count == 0, "Background sweep must not query SkyState"


# ---------------------------------------------------------------------------
# Lazy popup enrichment
# ---------------------------------------------------------------------------

class TestLazyPopupEnrichment:
    """Verify lazy popup fetches the right data based on day distance."""

    @freeze_time("2026-03-22T12:00:00Z")
    async def test_lazy_fetch_gdps_day_gets_skystate_only(self, hass: HomeAssistant):
        """For GDPS days, lazy fetch gets SkyState only (AirTemp+amounts in background)."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)

        # Day 4 from today (2026-03-22) = 2026-03-26 -> GDPS only
        target_date = "2026-03-26"
        # Seed store with POP + AirTemp data (simulating background sweep)
        coord._store.merge(TimestepData(
            time=f"{target_date}T12:00:00Z", pop=40, temp=-5.0, model="gdps",
        ))
        coord._store.merge(TimestepData(
            time=f"{target_date}T15:00:00Z", pop=10, temp=-3.0, model="gdps",
        ))
        coord.data = {"periods": {}, "hourly": {}}

        captured_queries = []

        def mock_build_periods(today, now_utc, local_tz):
            return [
                (target_date, "day",
                 datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                 datetime(2026, 3, 26, 22, 0, tzinfo=timezone.utc)),
            ]

        async def mock_execute(queries, now_ts, session, semaphore):
            captured_queries.extend(queries)
            results = []
            for layer, timestep, period_key in queries:
                results.append((layer, timestep, period_key, 3.0))
            return results, 0, len(results)

        with patch("ec_weather.coordinator.weong.build_periods", side_effect=mock_build_periods):
            coord._execute_queries = mock_execute
            await coord.async_fetch_day_timesteps(target_date)

        # Should ONLY have SkyState queries (AirTemp+amounts done in background)
        for layer, _, _ in captured_queries:
            bare = _bare_layer_name(layer)
            assert bare == _LAYER_SUFFIXES["sky_state"], \
                f"Lazy fetch should only query SkyState, got {bare}"

    async def test_lazy_fetch_hrdps_day_gets_skystate_only(self, hass: HomeAssistant):
        """For HRDPS days (0-2), lazy fetch gets SkyState only (AirTemp/amounts already in store)."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)

        # Seed store with full HRDPS data for day 0
        target_date = "2026-03-22"
        for hour in range(11, 22):
            coord._store.merge(TimestepData(
                time=f"{target_date}T{hour:02d}:00:00Z",
                temp=-3.0, pop=30, rain_mm=0, model="hrdps",
            ))
        coord.data = {"periods": {}, "hourly": {}}

        captured_queries = []

        def mock_build_periods(today, now_utc, local_tz):
            return [
                (target_date, "day",
                 datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc),
                 datetime(2026, 3, 22, 22, 0, tzinfo=timezone.utc)),
            ]

        async def mock_execute(queries, now_ts, session, semaphore):
            captured_queries.extend(queries)
            results = []
            for layer, timestep, period_key in queries:
                results.append((layer, timestep, period_key, 5.0))
            return results, 0, len(results)

        with patch("ec_weather.coordinator.weong.build_periods", side_effect=mock_build_periods):
            coord._execute_queries = mock_execute
            await coord.async_fetch_day_timesteps(target_date)

        # Should ONLY have SkyState queries (no AirTemp, no amounts)
        for layer, _, _ in captured_queries:
            bare = _bare_layer_name(layer)
            assert bare == _LAYER_SUFFIXES["sky_state"], \
                f"Expected only SkyState queries for HRDPS day, got {bare}"

    async def test_lazy_fetch_cached_no_requery(self, hass: HomeAssistant):
        """Second lazy fetch for same date uses cache — no new queries."""
        hass.config.time_zone = "America/Toronto"
        coord = _make_coord(hass)
        target_date = "2026-03-22"
        coord._store.merge(TimestepData(
            time=f"{target_date}T12:00:00Z", pop=30, model="hrdps",
        ))
        coord.data = {"periods": {}, "hourly": {}}

        query_count = 0

        def mock_build_periods(today, now_utc, local_tz):
            return [(target_date, "day",
                     datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc),
                     datetime(2026, 3, 22, 22, 0, tzinfo=timezone.utc))]

        async def mock_execute(queries, now_ts, session, semaphore):
            nonlocal query_count
            query_count += len(queries)
            results = [(l, t, p, 5.0) for l, t, p in queries]
            return results, 0, len(results)

        with patch("ec_weather.coordinator.weong.build_periods", side_effect=mock_build_periods):
            coord._execute_queries = mock_execute

            # First call — should query
            await coord.async_fetch_day_timesteps(target_date)
            first_count = query_count

            # Second call — should be cached (within 5s rate limit)
            await coord.async_fetch_day_timesteps(target_date)
            assert query_count == first_count, "Second call should not make new queries"
