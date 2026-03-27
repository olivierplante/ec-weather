"""ECWEonGCoordinator — WEonG precipitation data from GeoMet WMS."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from ..const import (
    DOMAIN,
    GEOMET_REQUEST_TIMEOUT,
    WEONG_CACHE_TTL_GDPS,
    WEONG_CACHE_TTL_HRDPS,
    WEONG_SEMAPHORE_LIMIT,
)
from ..api_client import TransientGeoMetError, query_geomet_feature_info
from ..timestep_store import TimestepData, TimestepStore
from .base import OnDemandCoordinator
from .weong_helpers import (
    _AMT_LAYERS_COLD,
    _AMT_LAYERS_TRANSITION,
    _AMT_LAYERS_WARM,
    _COLD_THRESHOLD,
    _GDPS_PREFIX,
    _LAYER_SUFFIXES,
    _WARM_THRESHOLD,
    _bare_layer_name,
    _model_from_layer,
    _models_for_day,
    _weong_layer_name,
    build_periods,
    build_timestep_data,
)

_LOGGER = logging.getLogger(__name__)

# HRDPS model runs at 00Z, 06Z, 12Z, 18Z with ~2h processing delay.
_HRDPS_RUN_HOURS = (0, 6, 12, 18)
_HRDPS_PROCESSING_DELAY_H = 2


def _expected_hrdps_model_run(now_utc: datetime) -> str:
    """Return the ISO timestamp of the latest HRDPS model run expected to be available.

    HRDPS runs at 00Z, 06Z, 12Z, 18Z. Each run takes ~2h to process,
    so the 06Z run becomes available around 08Z.

    Returns the model run time (not availability time) as an ISO string,
    e.g. "2026-03-22T06:00:00Z" when called at 08:30Z.
    """
    current_hour = now_utc.hour
    # Work backwards: find the latest run whose availability time has passed
    # Availability = run_hour + processing_delay
    latest_run_hour = None
    for run_hour in reversed(_HRDPS_RUN_HOURS):
        if current_hour >= run_hour + _HRDPS_PROCESSING_DELAY_H:
            latest_run_hour = run_hour
            break

    if latest_run_hour is not None:
        run_dt = now_utc.replace(
            hour=latest_run_hour, minute=0, second=0, microsecond=0,
        )
    else:
        # Before first run of the day (before 02Z) → previous day's 18Z
        yesterday = now_utc - timedelta(days=1)
        run_dt = yesterday.replace(hour=18, minute=0, second=0, microsecond=0)

    return run_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_model_run_availability(now_utc: datetime) -> datetime:
    """Return the UTC datetime when the next HRDPS model run becomes available.

    Availability times are run_hour + processing delay:
    00Z+2h=02Z, 06Z+2h=08Z, 12Z+2h=14Z, 18Z+2h=20Z.
    """
    availability_hours = [
        run + _HRDPS_PROCESSING_DELAY_H for run in _HRDPS_RUN_HOURS
    ]  # [2, 8, 14, 20]

    current_hour = now_utc.hour
    for avail_hour in availability_hours:
        if avail_hour > current_hour:
            return now_utc.replace(
                hour=avail_hour, minute=0, second=0, microsecond=0,
            )
        if avail_hour == current_hour and now_utc.minute == 0 and now_utc.second == 0:
            # Exactly at availability — next one
            continue

    # Past all today's runs → first run tomorrow (00Z + delay = 02Z)
    tomorrow = now_utc + timedelta(days=1)
    return tomorrow.replace(
        hour=availability_hours[0], minute=0, second=0, microsecond=0,
    )


class ECWEonGCoordinator(OnDemandCoordinator):
    """Fetches POP and conditional precip amounts from EC GeoMet WMS.

    Queries the Weather Elements on Grid (WEonG) layers via GetFeatureInfo
    point queries. Results are stored in a canonical TimestepStore, and
    periods{}/hourly{} views are derived projections of that store.
    """

    # Safety ceiling interval — used as initial interval before first fetch.
    # After each fetch, update_interval is set dynamically to the next model run.
    _SAFETY_INTERVAL_MINUTES = 360  # 6 hours
    # Short retry when expected model run data isn't available yet from GeoMet
    _RETRY_INTERVAL = timedelta(minutes=15)

    def __init__(
        self,
        hass: HomeAssistant,
        geomet_bbox: str,
        polling: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weong",
            interval=timedelta(minutes=self._SAFETY_INTERVAL_MINUTES),
            polling=polling,
        )
        self.geomet_bbox = geomet_bbox
        self._had_transient_errors: bool = False
        # Cache: (layer, time_str) -> (value, fetched_timestamp)
        # Model data doesn't change between runs (HRDPS every 6h, GDPS every 12h),
        # so we cache results and only re-query when the TTL expires.
        self._cache: dict[tuple[str, str], tuple[float | None, float]] = {}
        # Lock for concurrent day merges during progressive loading
        self._merge_lock = asyncio.Lock()
        # Timestep cache for lazy popup data: {date_str: (data_dict, fetched_ts)}
        self._timestep_cache: dict[str, tuple[dict, float]] = {}
        # Rate-limit: track last request timestamp per date_str
        self._timestep_request_ts: dict[str, float] = {}
        # Canonical timestep store — single source of truth for all WEonG data
        self._store = TimestepStore()
        # Latest HRDPS model run seen from GeoMet responses (for freshness)
        self._last_model_run: str | None = None
        # Timestamp of the last actual GeoMet fetch (not projection)
        self._last_fetch_ts: str | None = None

    def needs_refresh(self) -> bool:
        """Return True when new data should be fetched.

        Model-run-aware: returns True when a new HRDPS model run is
        available or when the coordinator has no data yet.
        """
        if not self.data:
            return True
        return not self._is_model_run_current()

    def _cache_ttl(self, layer: str) -> int:
        """Return cache TTL in seconds based on model type."""
        if layer.startswith(_GDPS_PREFIX):
            return WEONG_CACHE_TTL_GDPS
        return WEONG_CACHE_TTL_HRDPS

    async def _execute_queries(
        self,
        queries: list[tuple[str, datetime, tuple[str, str]]],
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> tuple[list[tuple[str, datetime, tuple[str, str], float | None]], int, int]:
        """Execute queries with caching. Returns (results, num_cached, num_fetched)."""
        cached_results: list[tuple[str, datetime, tuple[str, str], float | None]] = []
        uncached: list[tuple[str, datetime, tuple[str, str]]] = []

        for layer, timestep, period_key in queries:
            time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
            cached = self._cache.get((layer, time_str))
            if cached is not None:
                value, fetched_ts = cached
                if now_ts - fetched_ts < self._cache_ttl(layer):
                    cached_results.append((layer, timestep, period_key, value))
                    continue
            uncached.append((layer, timestep, period_key))

        fetched: list[tuple[str, datetime, tuple[str, str], float | None]] = []
        if uncached:
            async def _throttled(layer: str, timestep: datetime) -> float | None:
                async with semaphore:
                    return await self._query_feature_info(session, layer, timestep)

            results = await asyncio.gather(
                *[_throttled(layer, ts) for layer, ts, _ in uncached]
            )
            # Cache successful results and "no data" (None).
            # Do NOT cache transient errors — they should be retried next cycle.
            for (layer, timestep, period_key), value in zip(uncached, results):
                if value is self._TRANSIENT_ERROR:
                    # Treat as None for aggregation, but don't cache.
                    # Flag so staleness check forces re-fetch next time.
                    self._had_transient_errors = True
                    fetched.append((layer, timestep, period_key, None))
                    continue
                time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
                self._cache[(layer, time_str)] = (value, now_ts)
                fetched.append((layer, timestep, period_key, value))

        return cached_results + fetched, len(cached_results), len(uncached)

    def _build_timestep_info(
        self,
        periods: list[tuple[str, str, datetime, datetime]],
        today: date,
    ) -> list[tuple[datetime, tuple[str, str], str]]:
        """Build timestep info list from period definitions.

        Returns list of (timestep_utc, period_key, model) tuples.
        GDPS timesteps snap to 3h boundaries from 00Z.
        """
        timestep_info: list[tuple[datetime, tuple[str, str], str]] = []
        for date_str, period_type, utc_start, utc_end in periods:
            period_key = (date_str, period_type)
            days_ahead = max(0, (datetime.strptime(date_str, "%Y-%m-%d").date() - today).days)
            for model, step_h in _models_for_day(days_ahead):
                if model == "gdps":
                    hour = utc_start.hour
                    remainder = hour % 3
                    if remainder == 0:
                        t = utc_start.replace(minute=0, second=0, microsecond=0)
                    else:
                        t = (utc_start.replace(minute=0, second=0, microsecond=0)
                             + timedelta(hours=3 - remainder))
                else:
                    t = utc_start
                while t < utc_end:
                    timestep_info.append((t, period_key, model))
                    t += timedelta(hours=step_h)
        return timestep_info

    async def _fetch_day(
        self,
        day_periods: list[tuple[str, str, datetime, datetime]],
        today: date,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> list:
        """Background fetch: POP + AirTemp for all models, amounts for wet
        timesteps, SkyState for dry timesteps.

        Returns a flat list of (layer, timestep, period_key, value) result tuples.
        """
        timestep_info = self._build_timestep_info(day_periods, today)
        if not timestep_info:
            return []

        # POP + AirTemp for all models (HRDPS + GDPS)
        pop_suffix = _LAYER_SUFFIXES["precip_prob"]
        temp_suffix = _LAYER_SUFFIXES["air_temp"]
        always_queries = []
        for ts, pk, model in timestep_info:
            always_queries.append((_weong_layer_name(pop_suffix, model), ts, pk))
            always_queries.append((_weong_layer_name(temp_suffix, model), ts, pk))

        always_results, _, _ = await self._execute_queries(
            always_queries, now_ts, session, semaphore,
        )

        # Identify wet timesteps (POP > 0) and temperatures for amount queries
        wet_timesteps: set[tuple[datetime, str]] = set()
        temp_lookup: dict[tuple[datetime, str], float] = {}

        for layer, timestep, period_key, value in always_results:
            bare = _bare_layer_name(layer)
            model = _model_from_layer(layer)
            if bare == pop_suffix and value is not None and value > 0:
                wet_timesteps.add((timestep, model))
            elif bare == temp_suffix and value is not None:
                temp_lookup[(timestep, model)] = value

        # Amounts for all wet timesteps, filtered by temperature
        amt_results = []
        if wet_timesteps:
            amt_queries = []
            for ts, pk, model in timestep_info:
                if (ts, model) not in wet_timesteps:
                    continue
                temp = temp_lookup.get((ts, model))
                if temp is None:
                    layers = _AMT_LAYERS_TRANSITION
                elif temp > _WARM_THRESHOLD:
                    layers = _AMT_LAYERS_WARM
                elif temp < _COLD_THRESHOLD:
                    layers = _AMT_LAYERS_COLD
                else:
                    layers = _AMT_LAYERS_TRANSITION
                for key in layers:
                    layer = _weong_layer_name(_LAYER_SUFFIXES[key], model)
                    amt_queries.append((layer, ts, pk))
            amt_results, _, _ = await self._execute_queries(
                amt_queries, now_ts, session, semaphore,
            )

        # SkyState for all timesteps — needed for icon derivation on the
        # hourly card. Wet timesteps with POP > 0 but amounts = 0 still need
        # SkyState as fallback since derive_icon can't determine a precip icon.
        sky_queries = []
        sky_suffix = _LAYER_SUFFIXES["sky_state"]
        for ts, pk, model in timestep_info:
            sky_queries.append((_weong_layer_name(sky_suffix, model), ts, pk))

        sky_results = []
        if sky_queries:
            sky_results, _, _ = await self._execute_queries(
                sky_queries, now_ts, session, semaphore,
            )

        return always_results + amt_results + sky_results

    def _results_to_store(
        self,
        all_results: list[tuple[str, datetime, tuple[str, str], float | None]],
    ) -> int:
        """Merge raw query results into the canonical timestep store.

        Groups results by (timestep, model), delegates unit conversion and
        precip folding to build_timestep_data(), then merges into the store.

        Returns the count of failed (None-valued) results.
        """
        # Group results by (timestep, model) so we can build one TimestepData per timestep
        grouped: dict[tuple[str, str], dict[str, float | None]] = defaultdict(dict)
        total_failed = 0

        for layer, timestep, period_key, value in all_results:
            if value is None:
                total_failed += 1
                continue
            model = _model_from_layer(layer)
            bare = _bare_layer_name(layer)
            ts_iso = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
            key = (ts_iso, model)

            for suffix_key, suffix in _LAYER_SUFFIXES.items():
                if bare == suffix:
                    grouped[key][suffix_key] = value
                    break

        # Convert grouped data to TimestepData entries and merge
        for (ts_iso, model), values in grouped.items():
            entry = build_timestep_data(ts_iso, model, values)
            self._store.merge(entry)

        return total_failed

    def _project_output(
        self,
        periods: list[tuple[str, str, datetime, datetime]],
    ) -> dict:
        """Build the coordinator output from the canonical store.

        Projects the store into periods{} and hourly{} views that match
        the output format expected by sensor.py and transforms.py.
        """
        period_projection = self._store.project_periods(periods)
        hourly_projection = self._store.project_hourly()

        return {
            "periods": period_projection,
            "hourly": hourly_projection,
            "updated": self._last_fetch_ts,
        }

    def _is_model_run_current(self) -> bool:
        """Check if the cached model run matches what's expected to be available.

        Returns True if no new HRDPS model run is expected — safe to skip update.
        Returns False (proceed with update) when:
        - No cached model run yet (first fetch)
        - A newer model run should be available
        - weong_interval has elapsed (safety ceiling)
        """
        if self._last_model_run is None:
            return False  # first fetch
        now_utc = datetime.now(timezone.utc)
        expected = _expected_hrdps_model_run(now_utc)
        return self._last_model_run == expected

    async def _do_update(self) -> dict:
        """Orchestrate per-day parallel fetch with progressive publishing.

        Results are merged into the canonical store, which preserves SkyState
        from lazy fetches and handles progressive loading safely by construction.
        No snapshot/carry-forward workarounds needed.
        """

        # Skip if data is still current and no transient errors from last fetch.
        # The mixin calls needs_refresh() before triggering, but _do_update
        # can also be called directly (e.g. polling mode), so guard here too.
        if not self._had_transient_errors and not self.needs_refresh():
            _LOGGER.debug(
                "EC WEonG: skipping update — model run %s is current",
                self._last_model_run,
            )
            return self.data

        # Reset transient error flag — will be set during fetch if errors occur
        self._had_transient_errors = False
        _LOGGER.debug("EC WEonG: starting update")
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        today = dt_util.now().date()
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)

        periods = build_periods(today, now, local_tz)
        if not periods:
            _LOGGER.debug("EC WEonG: no periods to query")
            return {"periods": {}, "hourly": {}}

        # Prune stale entries from the store (>1h in the past)
        cutoff = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._store.prune_before(cutoff)

        # Group periods by date for per-day parallel processing
        periods_by_date: dict[str, list] = defaultdict(list)
        for period in periods:
            periods_by_date[period[0]].append(period)

        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)

        all_periods: list = list(periods)

        async def _process_day(date_str: str, day_periods: list) -> None:
            """Fetch one day and merge results progressively."""
            day_results = await self._fetch_day(
                day_periods, today, now_ts, session, semaphore,
            )
            async with self._merge_lock:
                self._results_to_store(day_results)
                try:
                    merged = self._project_output(all_periods)
                    self.async_set_updated_data(merged)
                except (KeyError, TypeError, ValueError):
                    _LOGGER.debug(
                        "EC WEonG: partial projection failed "
                        "(expected during progressive load)"
                    )

        # Launch all days in parallel
        await asyncio.gather(*[
            _process_day(date_str, day_periods)
            for date_str, day_periods in sorted(periods_by_date.items())
        ])

        # Record the actual fetch time
        self._last_fetch_ts = datetime.now(timezone.utc).isoformat()

        # Final projection from the store
        try:
            result = self._project_output(all_periods)
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC WEonG: failed to project store")
            if self.data:
                return self.data
            return {"periods": {}, "hourly": {}}

        # Prune HTTP cache entries for timesteps more than 1 hour in the past
        stale_keys = [k for k in self._cache if k[1] < cutoff]
        for k in stale_keys:
            del self._cache[k]

        # Prune rate-limit timestamps for dates no longer in forecast range
        valid_dates = {period[0] for period in periods}
        stale_dates = [d for d in self._timestep_request_ts if d not in valid_dates]
        for d in stale_dates:
            del self._timestep_request_ts[d]

        _LOGGER.debug(
            "EC WEonG: update complete — %d store entries, %d periods",
            len(self._store), len(periods),
        )

        self.mark_refreshed()

        # In polling mode, schedule next poll dynamically based on model runs.
        if self._polling:
            now_utc = datetime.now(timezone.utc)
            expected = _expected_hrdps_model_run(now_utc)
            if self._last_model_run != expected:
                # Fetched data still has old model run — retry shortly
                self.update_interval = self._RETRY_INTERVAL
                _LOGGER.debug(
                    "EC WEonG: model run %s not yet available, retry in %s",
                    expected, self._RETRY_INTERVAL,
                )
            else:
                # Got current data — schedule for next model run
                next_avail = _next_model_run_availability(now_utc)
                wait = next_avail - now_utc
                # Add 5 min buffer for processing variability
                self.update_interval = wait + timedelta(minutes=5)
                _LOGGER.debug(
                    "EC WEonG: next model run at %s, polling in %s",
                    next_avail, self.update_interval,
                )

        return result

    async def async_fetch_day_timesteps(self, date_str: str) -> None:
        """Lazy-fetch popup detail for a specific day's timesteps.

        Called by the ec_weather.fetch_day_timesteps service when the user
        opens a daily popup. What gets fetched depends on the model:

        - HRDPS days (0-2): SkyState only (AirTemp/amounts already in store
          from background sweep)
        - GDPS days (3+): AirTemp + amounts + SkyState (not fetched in background)

        Results merge into the canonical store and listeners are notified.
        Cached per-date with model-appropriate TTL.
        """

        now_mono = time.monotonic()

        # Rate-limit: skip if the same date was requested within the last 5 seconds
        last_request = self._timestep_request_ts.get(date_str, 0)
        if now_mono - last_request < 5:
            return  # rate-limited
        self._timestep_request_ts[date_str] = now_mono

        # Check timestep cache
        cached = self._timestep_cache.get(date_str)
        if cached is not None:
            _, fetched_ts = cached
            # Use HRDPS TTL as a safe default (shorter = fresher)
            if now_mono - fetched_ts < WEONG_CACHE_TTL_HRDPS:
                return  # cached, no work needed

        if not self.data:
            _LOGGER.debug("EC WEonG: no data yet, skipping timestep fetch for %s", date_str)
            return

        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        today = dt_util.now().date()
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)

        # Build periods for just this date
        all_periods = build_periods(today, now, local_tz)
        day_periods = [p for p in all_periods if p[0] == date_str]
        if not day_periods:
            _LOGGER.debug("EC WEonG: no periods for date %s", date_str)
            return

        # Build timesteps for this day
        timestep_info = self._build_timestep_info(day_periods, today)
        if not timestep_info:
            return

        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)

        # Lazy fetch: SkyState for all timesteps (POP + AirTemp + amounts
        # already in store from background sweep). SkyState is needed even
        # for wet timesteps when POP > 0 but amounts = 0.
        all_queries: list[tuple[str, datetime, tuple[str, str]]] = []
        for ts, pk, model in timestep_info:
            all_queries.append((
                _weong_layer_name(_LAYER_SUFFIXES["sky_state"], model), ts, pk,
            ))

        if not all_queries:
            self._timestep_cache[date_str] = ({}, now_mono)
            return

        results, _, _ = await self._execute_queries(
            all_queries, now_ts, session, semaphore,
        )

        # Merge all results into the canonical store
        self._results_to_store(results)

        # Re-project and publish updated data
        updated = self._project_output(all_periods)
        self.async_set_updated_data(updated)

        self._timestep_cache[date_str] = ({}, now_mono)

        # Evict stale cache entries — keep only dates within forecast range (7 days)
        if len(self._timestep_cache) > 7:
            oldest_key = min(self._timestep_cache, key=lambda k: self._timestep_cache[k][1])
            del self._timestep_cache[oldest_key]

        fetched_count = sum(1 for _, _, _, v in results if v is not None)
        _LOGGER.debug(
            "EC WEonG: lazy-fetched %d values for %s",
            fetched_count, date_str,
        )


    # Sentinel returned by _query_feature_info on transient errors.
    # Distinct from None (which means "GeoMet returned no data for this timestep").
    _TRANSIENT_ERROR = object()

    async def _query_feature_info(
        self, session: aiohttp.ClientSession, layer: str, timestep: datetime,
    ) -> float | None | object:
        """Query a single WEonG layer at one UTC timestep.

        Delegates to the standalone query_geomet_feature_info() in api_client.
        Translates TransientGeoMetError into the _TRANSIENT_ERROR sentinel
        that the coordinator's caching logic expects.

        Also captures reference_datetime from the response to track the
        current model run for freshness checks.

        Returns:
          float -- the value from GeoMet
          None -- GeoMet responded but had no data for this timestep
          _TRANSIENT_ERROR -- network/DNS error, should NOT be cached
        """
        try:
            value, ref_dt = await query_geomet_feature_info(
                session=session,
                geomet_bbox=self.geomet_bbox,
                layer=layer,
                timestep=timestep,
                timeout=GEOMET_REQUEST_TIMEOUT,
            )
            # Track the latest model run seen from any response
            if ref_dt is not None:
                self._last_model_run = ref_dt
            return value
        except TransientGeoMetError:
            return self._TRANSIENT_ERROR
