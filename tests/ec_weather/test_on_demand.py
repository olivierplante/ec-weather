"""Tests for new features: on-demand staleness, per-day parallel, lazy timesteps."""

import time
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant

from ec_weather.coordinator import ECWeatherCoordinator, ECWEonGCoordinator
from ec_weather.const import DEFAULT_WEATHER_INTERVAL

from .conftest import load_fixture


WEATHER_URL = (
    "https://api.weather.gc.ca/collections/citypageweather-realtime"
    "/items/on-118?f=json&lang=en&skipGeometry=true"
)


# ---------------------------------------------------------------------------
# On-demand staleness
# ---------------------------------------------------------------------------

class TestOnDemandStaleness:
    async def test_skips_when_fresh(self, hass: HomeAssistant, aioclient_mock):
        """Given recent refresh → second refresh returns cached data, no API call."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(WEATHER_URL, json=data)

        coord = ECWeatherCoordinator(hass, "on-118", language="en", interval_minutes=30)

        # First call fetches via async_refresh (sets self.data)
        await coord.async_refresh()
        assert coord.data is not None
        assert coord.data["current"]["temp"] is not None
        call_count_after_first = len(aioclient_mock.mock_calls)

        # Second call within interval should skip (return cached, no new API call)
        await coord.async_refresh()
        assert len(aioclient_mock.mock_calls) == call_count_after_first

    async def test_fetches_when_stale(self, hass: HomeAssistant, aioclient_mock):
        """Given old refresh → _async_update_data makes API calls."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(WEATHER_URL, json=data)

        coord = ECWeatherCoordinator(hass, "on-118", language="en", interval_minutes=30)

        # First call
        result1 = await coord._async_update_data()
        call_count_after_first = len(aioclient_mock.mock_calls)

        # Simulate time passing beyond interval
        coord._last_refresh_ts = time.monotonic() - 1900  # 31+ minutes ago

        # Second call should re-fetch
        result2 = await coord._async_update_data()
        assert len(aioclient_mock.mock_calls) > call_count_after_first

    async def test_alerts_have_no_staleness_check(self, hass: HomeAssistant, aioclient_mock):
        """Alerts coordinator always polls — no on-demand staleness."""
        from ec_weather.coordinator import ECAlertCoordinator

        alerts_url = (
            "https://api.weather.gc.ca/collections/weather-alerts/items"
            "?bbox=44.420,-76.700,46.420,-74.700&f=json&skipGeometry=true"
        )
        aioclient_mock.get(alerts_url, json=load_fixture("weather_alerts_empty.json"))

        coord = ECAlertCoordinator(
            hass, bbox="44.420,-76.700,46.420,-74.700", language="en"
        )
        # Alert coordinator should NOT have _last_refresh_ts (no on-demand)
        assert not hasattr(coord, '_last_refresh_ts') or coord._last_refresh_ts is None

        # Both calls should hit the API
        await coord._async_update_data()
        call_count_1 = len(aioclient_mock.mock_calls)
        await coord._async_update_data()
        call_count_2 = len(aioclient_mock.mock_calls)
        assert call_count_2 > call_count_1


# ---------------------------------------------------------------------------
# Configurable intervals
# ---------------------------------------------------------------------------

class TestConfigurableIntervals:
    def test_weather_coordinator_accepts_interval(self, hass: HomeAssistant):
        """Given custom interval → coordinator uses it."""
        coord = ECWeatherCoordinator(hass, "on-118", interval_minutes=60)
        assert coord._configured_interval == timedelta(minutes=60)

    def test_weather_coordinator_default_interval(self, hass: HomeAssistant):
        """Given no interval → uses default."""
        coord = ECWeatherCoordinator(hass, "on-118")
        assert coord._configured_interval == timedelta(minutes=DEFAULT_WEATHER_INTERVAL)

    def test_weong_coordinator_uses_safety_interval(self, hass: HomeAssistant):
        """WEonG uses fixed safety ceiling interval (not configurable)."""
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert coord._configured_interval == timedelta(
            minutes=ECWEonGCoordinator._SAFETY_INTERVAL_MINUTES
        )

    def test_on_demand_mode_no_auto_polling(self, hass: HomeAssistant):
        """On-demand coordinators have update_interval=None."""
        weather = ECWeatherCoordinator(hass, "on-118")
        weong = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert weather.update_interval is None
        assert weong.update_interval is None

    def test_alerts_always_polling(self, hass: HomeAssistant):
        """Alerts coordinator keeps a fixed update_interval."""
        from ec_weather.coordinator import ECAlertCoordinator
        alerts = ECAlertCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert alerts.update_interval is not None


# ---------------------------------------------------------------------------
# Per-day parallel (WEonG)
# ---------------------------------------------------------------------------

class TestPerDayParallel:
    def test_build_timestep_info_groups_by_model(self, hass: HomeAssistant):
        """_build_timestep_info produces HRDPS (1h) and GDPS (3h) timesteps."""
        from datetime import datetime, timezone

        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        today = datetime(2026, 3, 23).date()

        # Day 0 period (HRDPS)
        periods_day0 = [
            ("2026-03-23", "day",
             datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
             datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)),
        ]
        ts_info = coord._build_timestep_info(periods_day0, today)
        # HRDPS: 12 hours at 1h steps
        assert len(ts_info) == 12
        assert all(m == "hrdps" for _, _, m in ts_info)

        # Day 4 period (GDPS)
        periods_day4 = [
            ("2026-03-27", "day",
             datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc),
             datetime(2026, 3, 27, 22, 0, tzinfo=timezone.utc)),
        ]
        ts_info = coord._build_timestep_info(periods_day4, today)
        # GDPS: 12 hours at 3h steps = 4 timesteps
        assert len(ts_info) == 4
        assert all(m == "gdps" for _, _, m in ts_info)


# ---------------------------------------------------------------------------
# Background fetch includes SkyState for all timesteps
# ---------------------------------------------------------------------------

class TestBackgroundFetchSkyState:
    async def test_fetch_day_includes_sky_state_for_dry_timesteps(self, hass: HomeAssistant):
        """Background _fetch_day must query SkyState for dry timesteps (POP=0)."""
        from datetime import datetime, timezone
        from ec_weather.coordinator.weong_helpers import _LAYER_SUFFIXES

        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        today = datetime(2026, 3, 23).date()

        day_periods = [
            ("2026-03-23", "day",
             datetime(2026, 3, 23, 14, 0, tzinfo=timezone.utc),
             datetime(2026, 3, 23, 17, 0, tzinfo=timezone.utc)),
        ]

        queried_layers: list[str] = []

        async def mock_execute(queries, now_ts, session, semaphore):
            results = []
            for layer, ts, pk in queries:
                queried_layers.append(layer)
                if "Precip-Prob" in layer:
                    results.append((layer, ts, pk, 0.0))
                elif "AirTemp" in layer:
                    results.append((layer, ts, pk, -5.0))
                else:
                    results.append((layer, ts, pk, 3.0))
            return results, 0, len(results)

        coord._execute_queries = mock_execute

        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        session = async_get_clientsession(hass)
        semaphore = __import__("asyncio").Semaphore(10)

        await coord._fetch_day(day_periods, today, time.time(), session, semaphore)

        sky_suffix = _LAYER_SUFFIXES["sky_state"]
        sky_queries = [l for l in queried_layers if sky_suffix in l]
        assert len(sky_queries) > 0, "Background fetch must include SkyState queries"

    async def test_fetch_day_includes_sky_state_for_wet_timesteps(self, hass: HomeAssistant):
        """Background _fetch_day must also query SkyState for wet timesteps.

        POP > 0 with amounts = 0 is common (chance of precip but no actual
        accumulation). SkyState is needed as fallback for icon derivation.
        """
        from datetime import datetime, timezone
        from ec_weather.coordinator.weong_helpers import _LAYER_SUFFIXES

        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        today = datetime(2026, 3, 23).date()

        day_periods = [
            ("2026-03-23", "day",
             datetime(2026, 3, 23, 14, 0, tzinfo=timezone.utc),
             datetime(2026, 3, 23, 17, 0, tzinfo=timezone.utc)),
        ]

        queried_layers: list[str] = []

        async def mock_execute(queries, now_ts, session, semaphore):
            results = []
            for layer, ts, pk in queries:
                queried_layers.append(layer)
                if "Precip-Prob" in layer:
                    results.append((layer, ts, pk, 40.0))  # wet but no amounts
                elif "AirTemp" in layer:
                    results.append((layer, ts, pk, -5.0))
                else:
                    results.append((layer, ts, pk, 3.0))
            return results, 0, len(results)

        coord._execute_queries = mock_execute

        from homeassistant.helpers.aiohttp_client import async_get_clientsession as _get
        session = _get(hass)
        semaphore = __import__("asyncio").Semaphore(10)

        await coord._fetch_day(day_periods, today, time.time(), session, semaphore)

        sky_suffix = _LAYER_SUFFIXES["sky_state"]
        sky_queries = [l for l in queried_layers if sky_suffix in l]
        assert len(sky_queries) > 0, "SkyState must be fetched even for wet timesteps"


# ---------------------------------------------------------------------------
# Lazy timestep fetch
# ---------------------------------------------------------------------------

class TestLazyTimestepFetch:
    def test_timestep_cache_initialized(self, hass: HomeAssistant):
        """WEonG coordinator has a timestep cache."""
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert hasattr(coord, '_timestep_cache')
        assert coord._timestep_cache == {}

    def test_merge_lock_initialized(self, hass: HomeAssistant):
        """WEonG coordinator has a merge lock for concurrent day tasks."""
        import asyncio
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert hasattr(coord, '_merge_lock')
        assert isinstance(coord._merge_lock, asyncio.Lock)

    async def test_lazy_fetch_updates_sky_state(self, hass: HomeAssistant):
        """Given service call with date → SkyState merged into existing data."""
        from datetime import datetime, timezone
        from ec_weather.timestep_store import TimestepData

        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")

        # Seed the canonical store with existing timesteps (no sky_state)
        coord._store.merge(TimestepData(
            time="2026-03-23T12:00:00Z", pop=10, temp=-5.0, model="hrdps",
        ))
        coord._store.merge(TimestepData(
            time="2026-03-23T15:00:00Z", pop=5, temp=-3.0, model="hrdps",
        ))

        # Set coord.data so the lazy fetch doesn't bail early
        coord.data = {"periods": {}, "hourly": {}}

        # Mock build_periods to return the date we want
        def mock_build_periods(today, now, local_tz):
            return [
                ("2026-03-23", "day",
                 datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
                 datetime(2026, 3, 23, 22, 0, tzinfo=timezone.utc)),
            ]

        # Mock _execute_queries to return SkyState values
        async def mock_execute(queries, now_ts, session, semaphore):
            results = []
            for layer, timestep, period_key in queries:
                results.append((layer, timestep, period_key, 3.0))
            return results, 0, len(results)

        from unittest.mock import patch
        with patch("ec_weather.coordinator.weong.build_periods", side_effect=mock_build_periods):
            coord._execute_queries = mock_execute
            await coord.async_fetch_day_timesteps("2026-03-23")

        # Verify sky_state was merged into the store and projected into output
        period = coord.data["periods"][("2026-03-23", "day")]
        for ts in period["timesteps"]:
            assert ts["sky_state"] == 3.0

    async def test_lazy_fetch_cached_on_second_call(self, hass: HomeAssistant):
        """Given repeated service call → second call uses cache, no queries."""
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")

        coord.data = {
            "periods": {
                ("2026-03-23", "day"): {
                    "pop": 0, "rain_amt_mm": None, "snow_amt_cm": None,
                    "timesteps": [
                        {"time": "2026-03-23T12:00:00Z", "pop": 0,
                         "rain_mm": None, "snow_cm": None,
                         "temp_c": -5, "sky_state": None},
                    ],
                },
            },
            "hourly": {},
        }

        query_count = 0
        original_execute = coord._execute_queries

        async def mock_execute(queries, now_ts, session, semaphore):
            nonlocal query_count
            query_count += len(queries)
            results = [
                (layer, ts, pk, 5.0) for layer, ts, pk in queries
            ]
            return results, 0, len(results)

        coord._execute_queries = mock_execute

        # First call fetches
        await coord.async_fetch_day_timesteps("2026-03-23")
        first_count = query_count

        # Second call should be cached — no new queries
        await coord.async_fetch_day_timesteps("2026-03-23")
        assert query_count == first_count  # no additional queries

    async def test_lazy_fetch_skips_when_no_data(self, hass: HomeAssistant):
        """Given no coordinator data → lazy fetch does nothing."""
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        coord.data = None

        # Should not crash
        await coord.async_fetch_day_timesteps("2026-03-23")
        assert coord._timestep_cache == {}  # nothing cached


# ---------------------------------------------------------------------------
# Polling modes
# ---------------------------------------------------------------------------

class TestPollingModes:
    def test_minimal_mode_all_on_demand(self, hass: HomeAssistant):
        """Minimal mode: weather, AQHI, WEonG all on-demand (update_interval=None)."""
        weather = ECWeatherCoordinator(hass, "on-118", polling=False)
        from ec_weather.coordinator import ECAQHICoordinator
        aqhi = ECAQHICoordinator(hass, None, polling=False)
        weong = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")

        assert weather.update_interval is None
        assert aqhi.update_interval is None
        assert weong.update_interval is None

    def test_efficient_mode_weather_and_aqhi_poll(self, hass: HomeAssistant):
        """Efficient mode: weather and AQHI poll, WEonG always on-demand."""
        weather = ECWeatherCoordinator(hass, "on-118", polling=True)
        from ec_weather.coordinator import ECAQHICoordinator
        aqhi = ECAQHICoordinator(hass, None, polling=True)
        weong = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")

        assert weather.update_interval is not None
        assert aqhi.update_interval is not None
        assert weong.update_interval is None

    def test_full_mode_everything_polls(self, hass: HomeAssistant):
        """Full mode: all coordinators poll (WEonG uses dynamic model-run-aware interval)."""
        weather = ECWeatherCoordinator(hass, "on-118", polling=True)
        from ec_weather.coordinator import ECAQHICoordinator
        aqhi = ECAQHICoordinator(hass, None, polling=True)
        weong = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700", polling=True)

        assert weather.update_interval is not None
        assert aqhi.update_interval is not None
        assert weong.update_interval is not None

    def test_polling_uses_configured_interval(self, hass: HomeAssistant):
        """When polling=True, update_interval matches configured interval."""
        weather = ECWeatherCoordinator(
            hass, "on-118", interval_minutes=60, polling=True,
        )
        assert weather.update_interval == timedelta(minutes=60)

    def test_alerts_always_poll_regardless_of_mode(self, hass: HomeAssistant):
        """Alerts coordinator always has a fixed update_interval."""
        from ec_weather.coordinator import ECAlertCoordinator
        alerts = ECAlertCoordinator(hass, "44.420,-76.700,46.420,-74.700")
        assert alerts.update_interval is not None

    def test_aqhi_interval_configurable(self, hass: HomeAssistant):
        """AQHI interval can be customized."""
        from ec_weather.coordinator import ECAQHICoordinator
        aqhi = ECAQHICoordinator(hass, None, interval_minutes=60, polling=True)
        assert aqhi.update_interval == timedelta(minutes=60)


class TestTransientErrorNotCached:
    async def test_transient_error_not_cached(self, hass: HomeAssistant):
        """DNS/timeout errors from GeoMet must NOT be cached."""
        coord = ECWEonGCoordinator(hass, "44.420,-76.700,46.420,-74.700")

        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).timestamp()
        session = None  # not used since we mock _query_feature_info
        semaphore = __import__("asyncio").Semaphore(20)

        ts = datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc)
        period_key = ("2026-03-25", "day")
        layer = "GDPS-WEonG_15km_Precip-Prob.3h"

        # Mock _query_feature_info to return TRANSIENT_ERROR
        async def mock_query(session, layer, timestep):
            return coord._TRANSIENT_ERROR

        coord._query_feature_info = mock_query

        queries = [(layer, ts, period_key)]
        results, cached_count, fetched_count = await coord._execute_queries(
            queries, now_ts, session, semaphore,
        )

        # Result should be None (treated as no data for aggregation)
        assert results[0][3] is None

        # Cache should be EMPTY — transient error was not stored
        time_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert (layer, time_str) not in coord._cache
