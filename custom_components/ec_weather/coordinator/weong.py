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
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CACHE_TTL_GEPS,
    DOMAIN,
    GEOMET_REQUEST_TIMEOUT,
    STORAGE_SAVE_DELAY,
    STORAGE_SCHEMA_VERSION,
    STORAGE_VERSION,
    WEONG_BACKOFF_FIRST_SECONDS,
    WEONG_BACKOFF_SECOND_SECONDS,
    WEONG_CACHE_TTL_HRDPS,
    WEONG_CACHE_TTL_RDPS,
    WEONG_CHUNK_DELAY_SECONDS,
    WEONG_DAY_COMPLETE_MIN_RATIO,
    WEONG_SEMAPHORE_LIMIT,
)
from ..api_client import (
    RateLimitedError,
    TransientGeoMetError,
    query_geomet_feature_info,
)
from ..timestep_store import TimestepData, TimestepStore
from .base import OnDemandCoordinator
from .extended_helpers import GEPS_POP_12H, GEPS_TEMPERATURE_P50, geps_window_for
from .extended import (
    GEPS_QUERY_TAG,
    OUTLOOK_FIRST_DAY,
    build_geps_timesteps,
    build_outlook_entry,
    build_precip_windows,
    days_ahead_for,
    expected_geps_run,
    geps_timesteps_for_periods,
    geps_windows_for_periods,
    index_results,
    is_geps_day,
    outlook_dates,
    outlook_sample_points,
    plan_base_queries,
    plan_outlook_base_queries,
    plan_pop_queries,
    plan_wet_queries,
    wet_window_ends,
)
from .weong_helpers import (
    _AMT_LAYERS_COLD,
    _AMT_LAYERS_TRANSITION,
    _AMT_LAYERS_WARM,
    _COLD_THRESHOLD,
    _RDPS_PREFIX,
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

# RDPS-WEonG forecast horizon: layers extend to model_run + 84h. Timesteps
# past this are not generated, so far days (5-6) stay honestly "unavailable".
_RDPS_HORIZON_HOURS = 84


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
        forecast_days: int = 7,
        entry_id: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weong",
            interval=timedelta(minutes=self._SAFETY_INTERVAL_MINUTES),
            polling=polling,
        )
        self.geomet_bbox = geomet_bbox
        # Persistent forecast cache. One Store per config entry (key
        # "ec_weather.<entry_id>"). None disables persistence — the coordinator
        # still works fully in memory, which keeps unit tests that construct it
        # without an entry_id unaffected.
        self._entry_id = entry_id
        self._persist_store: Store | None = (
            Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
            if entry_id is not None
            else None
        )
        # Extended-forecast scope (phase C): 7 official days (default), or
        # 10/14 to append GEPS outlook rows for the calendar days beyond EC's
        # 7-day list. Read once at setup; the options flow reloads the entry on
        # change, so a new coordinator picks up the new value.
        self._forecast_days = forecast_days
        self._had_transient_errors: bool = False
        # Set when a wave leaves any day below the completeness threshold, so
        # the skip-guard and polling scheduler know to retry soon (F2).
        self._had_incomplete_days: bool = False
        # Count of HTTP 429s seen during the current wave — drives the two-step
        # backoff. Reset at the start of each _do_update (F4).
        self._rate_limit_hits: int = 0
        # Cache: cache_key -> (value, fetched_timestamp). The key is
        # (layer, time_str) for HRDPS/RDPS; GEPS layers additionally fold in the
        # expected GEPS run (see _cache_key) so a newly published run misses the
        # stale entry. Model data doesn't change between runs (HRDPS and RDPS
        # both every 6h), so we cache results and only re-query when the TTL
        # expires or — for GEPS — the expected run rolls over.
        self._cache: dict[tuple[str, ...], tuple[float | None, float]] = {}
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
        # Dates (ISO "YYYY-MM-DD") whose queries have completed at least once.
        # A day joins this set even when it produced zero timesteps — days past
        # the RDPS 84h horizon (5-6) generate no timesteps. Attempted-and-empty
        # must be distinguishable from not-yet-fetched (pending) downstream.
        self._completed_days: set[str] = set()
        # Timestamp of the last actual GeoMet fetch (not projection)
        self._last_fetch_ts: str | None = None
        # Per-day GEPS precip band payload (phase B): {date_str: [window, ...]}.
        # Additive; only geps days (4-6) get an entry, projected onto the daily
        # forecast attribute for the card's future-spanning precip vessels.
        self._precip_windows: dict[str, list[dict]] = {}
        # Per-date GEPS outlook payload (phase C): {date_str: outlook_entry}.
        # Populated only when forecast_days > 7, for the calendar days beyond
        # the official 7. Appended to the daily forecast attribute; the store
        # is untouched (outlook days carry no timeline).
        self._outlook: dict[str, dict] = {}
        # Day-7 (last official day) overnight-low backfill (refinement 2).
        # EC's citypage publishes the 7th day without its night period until
        # later in the day; when extended is enabled the outlook wave samples
        # the GEPS night trough so the merge can fill ONLY the missing low /
        # night POP. None when extended is off. Shape:
        # {"date": str, "temp_low": int | None, "pop_night": int | None}.
        self._day7_backfill: dict | None = None

    def needs_refresh(self) -> bool:
        """Return True when new data should be fetched.

        Model-run-aware: returns True when a new HRDPS model run is
        available or when the coordinator has no data yet.
        """
        if not self.data:
            return True
        return not self._is_model_run_current()

    def _cache_ttl(self, layer: str) -> int:
        """Return cache TTL in seconds based on model type.

        GEPS layers cache for 12h (their run cadence), so the extended wave
        fetches once per new GEPS run instead of on every WEonG refresh.
        """
        if layer.startswith("GEPS."):
            return CACHE_TTL_GEPS
        if layer.startswith(_RDPS_PREFIX):
            return WEONG_CACHE_TTL_RDPS
        return WEONG_CACHE_TTL_HRDPS

    def _cache_key(
        self, layer: str, time_str: str, now_ts: float,
    ) -> tuple[str, ...]:
        """Build the query-cache key for one (layer, timestep) at fetch time.

        HRDPS/RDPS keep the plain ``(layer, time_str)`` key — their freshness is
        handled by the model-run scheduler and their 6h TTL. GEPS layers do NOT
        pin a reference run (they query the latest published run), so a value
        cached under the previous run would otherwise keep being served until its
        12h TTL expired. Folding the expected GEPS run into the key makes a
        refresh that fires after a new run publishes miss the stale entry and
        refetch the fresh run; while no new run has published the key is
        unchanged and the cache serves as before — zero extra API queries.
        """
        if layer.startswith("GEPS."):
            now_utc = datetime.fromtimestamp(now_ts, tz=timezone.utc)
            run = expected_geps_run(now_utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return (layer, time_str, run)
        return (layer, time_str)

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
            cached = self._cache.get(self._cache_key(layer, time_str, now_ts))
            if cached is not None:
                value, fetched_ts = cached
                if now_ts - fetched_ts < self._cache_ttl(layer):
                    cached_results.append((layer, timestep, period_key, value))
                    continue
            uncached.append((layer, timestep, period_key))

        fetched: list[tuple[str, datetime, tuple[str, str], float | None]] = []
        if uncached:
            async def _throttled(layer: str, timestep: datetime):
                async with semaphore:
                    return await self._query_feature_info(session, layer, timestep)

            # Cold-start pacing (F4b): run the uncached queries in
            # semaphore-sized chunks with a short delay between chunks, so a
            # reboot does not spike hundreds of near-concurrent requests into a
            # possibly-degraded server.
            chunk_size = WEONG_SEMAPHORE_LIMIT
            for chunk_start in range(0, len(uncached), chunk_size):
                chunk = uncached[chunk_start:chunk_start + chunk_size]
                chunk_results = await asyncio.gather(
                    *[_throttled(layer, ts) for layer, ts, _ in chunk]
                )

                # Honor 429 (F4a): if this chunk was rate-limited, pause the
                # wave briefly before continuing.
                if any(value is self._RATE_LIMITED for value in chunk_results):
                    await self._apply_rate_limit_backoff()

                # Cache successful results and "no data" (None). Do NOT cache
                # failures — transient errors and 429s must be retried (F1).
                for (layer, timestep, period_key), value in zip(chunk, chunk_results):
                    if value is self._TRANSIENT_ERROR or value is self._RATE_LIMITED:
                        # Treat as None for aggregation, but never cache.
                        # Flag so the staleness check forces a re-fetch.
                        self._had_transient_errors = True
                        fetched.append((layer, timestep, period_key, None))
                        continue
                    time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
                    self._cache[self._cache_key(layer, time_str, now_ts)] = (
                        value, now_ts,
                    )
                    fetched.append((layer, timestep, period_key, value))

                # Pace before the next chunk (never after the last one).
                if chunk_start + chunk_size < len(uncached):
                    await asyncio.sleep(WEONG_CHUNK_DELAY_SECONDS)

        return cached_results + fetched, len(cached_results), len(uncached)

    async def _apply_rate_limit_backoff(self) -> None:
        """Pause the wave briefly after a 429 (F4a): short on the first hit,
        longer on the second or later. Simple two-step backoff — no framework.
        """
        self._rate_limit_hits += 1
        delay = (
            WEONG_BACKOFF_FIRST_SECONDS
            if self._rate_limit_hits <= 1
            else WEONG_BACKOFF_SECOND_SECONDS
        )
        _LOGGER.info(
            "EC WEonG: GeoMet returned HTTP 429; pausing %ds before continuing "
            "(rate-limit hit #%d)", delay, self._rate_limit_hits,
        )
        await asyncio.sleep(delay)

    def _weong_base_completeness(
        self,
        results: list[tuple[str, datetime, tuple[str, str], float | None]],
    ) -> tuple[int, int]:
        """Return (succeeded, total) for a day's base POP+AirTemp queries.

        The "base" is the always-run POP and AirTemp layers — one of each per
        timestep. A failed query surfaces as a None value (never cached), so
        counting non-None base values measures how much of the day arrived.
        POP=0 is a real value (a dry timestep), so it counts as a success.
        """
        pop_suffix = _LAYER_SUFFIXES["precip_prob"]
        temp_suffix = _LAYER_SUFFIXES["air_temp"]
        total = 0
        succeeded = 0
        for layer, _ts, _pk, value in results:
            if _bare_layer_name(layer) in (pop_suffix, temp_suffix):
                total += 1
                if value is not None:
                    succeeded += 1
        return succeeded, total

    def _is_day_complete(
        self,
        base_succeeded: int,
        base_total: int,
        geps_entries: list[TimestepData],
    ) -> bool:
        """Decide whether a day's fetch counts as complete (F2).

        A day is complete when it either had nothing to fetch (no base timesteps
        and no GEPS entries — legitimately empty past the 84h horizon) or enough
        of its base queries returned data. Below WEONG_DAY_COMPLETE_MIN_RATIO the
        day stays "pending" so the existing 15-minute retry refetches it instead
        of caching the holes.
        """
        geps_total = len(geps_entries)
        geps_succeeded = sum(1 for entry in geps_entries if entry.temp is not None)
        total = base_total + geps_total
        if total == 0:
            return True  # nothing to fetch — a legitimate empty answer
        succeeded = base_succeeded + geps_succeeded
        return succeeded / total >= WEONG_DAY_COMPLETE_MIN_RATIO

    async def _process_day(
        self,
        date_str: str,
        day_periods: list,
        today: date,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        all_periods: list,
    ) -> None:
        """Fetch one day (WEonG + extended GEPS) and merge progressively.

        Whatever data arrived always merges into the store (partial display is
        fine). The day is only marked done (_completed_days) when its base
        queries cleared the completeness threshold; a partial day stays out of
        the set so it reads as "pending" and the 15-minute retry refetches it
        rather than the holes being cached and served until the next model run.
        """
        day_results = await self._fetch_day(
            day_periods, today, now_ts, session, semaphore,
        )
        geps_entries, geps_windows = await self._fetch_geps_day(
            date_str, day_periods, today, now_ts, session, semaphore,
        )
        async with self._merge_lock:
            self._results_to_store(day_results)
            # GEPS entries are already synthesized TimestepData; merge them
            # straight in. Store priority keeps RDPS ahead of GEPS on overlap.
            for entry in geps_entries:
                self._store.merge(entry)
            if geps_windows is not None:
                self._precip_windows[date_str] = geps_windows

            # Completeness gate (F2). Zero base queries (past the 84h horizon,
            # not a GEPS day) counts as complete — attempted-and-empty is a real
            # answer, not a pending state. A day that fetched but landed below
            # the threshold stays pending for the retry.
            base_succeeded, base_total = self._weong_base_completeness(day_results)
            if self._is_day_complete(base_succeeded, base_total, geps_entries):
                self._completed_days.add(date_str)
            else:
                self._had_incomplete_days = True
                self._completed_days.discard(date_str)

            try:
                merged = self._project_output(all_periods)
                self.async_set_updated_data(merged)
            except (KeyError, TypeError, ValueError):
                _LOGGER.debug(
                    "EC WEonG: partial projection failed "
                    "(expected during progressive load)"
                )

    def _build_timestep_info(
        self,
        periods: list[tuple[str, str, datetime, datetime]],
        today: date,
    ) -> list[tuple[datetime, tuple[str, str], str]]:
        """Build timestep info list from period definitions.

        Returns list of (timestep_utc, period_key, model) tuples. Every model
        is hourly. Timesteps are capped at the RDPS 84h horizon (measured from
        the expected model run), so days wholly past the horizon generate no
        timesteps and stay honestly "unavailable" downstream.
        """
        horizon_cap = self._horizon_cap()
        timestep_info: list[tuple[datetime, tuple[str, str], str]] = []
        for date_str, period_type, utc_start, utc_end in periods:
            period_key = (date_str, period_type)
            days_ahead = max(0, (datetime.strptime(date_str, "%Y-%m-%d").date() - today).days)
            for model, step_h in _models_for_day(days_ahead):
                if model == "geps":
                    # The extended GEPS wave (_fetch_geps_day) owns these — its
                    # layers, 3h grid and day-6 horizon differ from WEonG's.
                    continue
                t = utc_start
                while t < utc_end:
                    if t > horizon_cap:
                        break  # past the 84h horizon — stop generating
                    timestep_info.append((t, period_key, model))
                    t += timedelta(hours=step_h)
        return timestep_info

    def _horizon_cap(self) -> datetime:
        """Return the latest UTC timestep that can carry data.

        RDPS-WEonG layers extend to model_run + 84h. Beyond that there is no
        forecast data, so the coordinator does not generate those timesteps.
        """
        now_utc = datetime.now(timezone.utc)
        expected_run_iso = _expected_hrdps_model_run(now_utc)
        expected_run = datetime.strptime(
            expected_run_iso, "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
        return expected_run + timedelta(hours=_RDPS_HORIZON_HOURS)

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

        # POP + AirTemp for all models (HRDPS + RDPS)
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

    async def _fetch_geps_day(
        self,
        date_str: str,
        day_periods: list[tuple[str, str, datetime, datetime]],
        today: date,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> tuple[list[TimestepData], list[dict] | None]:
        """Fetch the GEPS extended timeline for one calendar day (days 4-6).

        Runs the GEPS wave beside the WEonG per-day fetch: 3h TT/HMX/NT p50 for
        every step, a POP (PRMM ERGE1) query per covering 12h window, and — only
        for wet windows (POP >= 30) — the amount band (ERC25/75) and precip-type
        medians (RNMM/SNMM). Values fold into synthesized ``TimestepData``
        (model="geps") plus a per-day ``precip_windows`` band payload.

        Returns ``([], None)`` for days outside the GEPS coverage band, so the
        caller can call it unconditionally. All queries reuse the cached executor
        (12h GEPS TTL), keeping the wave to one fetch per GEPS run.
        """
        if not is_geps_day(days_ahead_for(date_str, today)):
            return [], None

        steps = geps_timesteps_for_periods(day_periods)
        if not steps:
            return [], None

        half_windows = geps_windows_for_periods(day_periods)
        # Distinct covering windows: every step's window plus each half's window.
        window_ends = sorted({
            geps_window_for(step)[1] for step in steps
        } | {half["end"] for half in half_windows})

        # Phase 1 — POP per 12h window (drives wet-gating and stepwise POP).
        pop_results, _, _ = await self._execute_queries(
            plan_pop_queries(window_ends), now_ts, session, semaphore,
        )
        pop_values = index_results(pop_results)
        pop_by_window_end = {
            end: pop_values.get((GEPS_POP_12H, end)) for end in window_ends
        }

        # Phase 2 — always-run continuous fields (TT/HMX/NT p50 per 3h step).
        base_results, _, _ = await self._execute_queries(
            plan_base_queries(steps), now_ts, session, semaphore,
        )

        # Phase 3 — wet windows only: amount band + precip-type medians.
        wet_ends = wet_window_ends(pop_by_window_end)
        wet_results: list = []
        if wet_ends:
            wet_results, _, _ = await self._execute_queries(
                plan_wet_queries(wet_ends), now_ts, session, semaphore,
            )

        values = index_results(base_results)
        values.update(index_results(wet_results))

        entries = build_geps_timesteps(steps, pop_by_window_end, values)
        precip_windows = build_precip_windows(half_windows, pop_by_window_end, values)
        return entries, precip_windows

    async def _fetch_outlook(
        self,
        today: date,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        local_tz,
    ) -> None:
        """Fetch and build the GEPS outlook entries (calendar days beyond 7).

        No-op in mode 7. In modes 10/14 each outlook date is fetched with the
        cached GEPS executor (12h TTL), so the wave runs once per GEPS run.
        Rebuilds ``self._outlook`` from scratch each run — the cache makes a
        full refetch cheap and keeps stale (rolled-off) dates from lingering.
        """
        if self._forecast_days <= 7:
            self._outlook = {}
            return

        dates = outlook_dates(today, self._forecast_days)
        entries = await asyncio.gather(*[
            self._fetch_one_outlook_day(
                date_str, local_tz, now_ts, session, semaphore,
            )
            for date_str in dates
        ])
        self._outlook = {
            date_str: entry
            for date_str, entry in zip(dates, entries)
            if entry is not None
        }

    async def _fetch_one_outlook_day(
        self,
        date_str: str,
        local_tz,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> dict | None:
        """Build one outlook day: POP (wet-gate) -> continuous fields -> band."""
        points = outlook_sample_points(date_str, local_tz)
        window_ends = [points["day_window_end"], points["night_window_end"]]

        # Phase 1 — POP per 12h half-window (drives wet-gating).
        pop_results, _, _ = await self._execute_queries(
            plan_pop_queries(window_ends), now_ts, session, semaphore,
        )
        pop_values = index_results(pop_results)
        pop_by_window_end = {
            end: pop_values.get((GEPS_POP_12H, end)) for end in window_ends
        }

        # Phase 2 — continuous fields at the two representative hours.
        base_results, _, _ = await self._execute_queries(
            plan_outlook_base_queries(points["day_rep"], points["night_rep"]),
            now_ts, session, semaphore,
        )

        # Phase 3 — wet windows only: amount band + precip-type medians.
        wet_ends = wet_window_ends(pop_by_window_end)
        wet_results: list = []
        if wet_ends:
            wet_results, _, _ = await self._execute_queries(
                plan_wet_queries(wet_ends), now_ts, session, semaphore,
            )

        values = index_results(base_results)
        values.update(index_results(wet_results))
        entry = build_outlook_entry(date_str, points, pop_by_window_end, values)

        # No half-built outlook rows (F3): a day missing either temp median (its
        # low or high) is not a usable row. Return None so this date stays out of
        # self._outlook and the projection re-emits its pending skeleton, exactly
        # like an unfetched day — the next wave retries it.
        if entry.get("temp_low") is None or entry.get("temp_high") is None:
            return None
        return entry

    async def _fetch_day7_backfill(
        self,
        today: date,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        local_tz,
    ) -> None:
        """Sample the GEPS night trough for the last official day's overnight low.

        No-op in mode 7. When extended is enabled, EC's 7th (last official) day
        may lack its night period (the citypage publishes it later in the day),
        so its daily row reads as a half-empty hole above the outlook rows. We
        sample GEPS TT p50 at the ~05:00 local trough of the following morning
        (the same trough convention ``outlook_sample_points`` uses) plus the
        covering 12h ERGE1 POP, and stash them in ``self._day7_backfill``. The
        merge fills ONLY the missing low / night POP — published values stay
        untouched. Two queries, on the cached GEPS executor (12h TTL).
        """
        if self._forecast_days <= 7:
            self._day7_backfill = None
            return

        # Last official day is the day just before the first outlook day.
        last_official = (today + timedelta(days=OUTLOOK_FIRST_DAY - 1)).isoformat()
        points = outlook_sample_points(last_official, local_tz)
        night_rep = points["night_rep"]
        night_window_end = points["night_window_end"]

        results, _, _ = await self._execute_queries(
            [
                (GEPS_TEMPERATURE_P50, night_rep, GEPS_QUERY_TAG),
                (GEPS_POP_12H, night_window_end, GEPS_QUERY_TAG),
            ],
            now_ts, session, semaphore,
        )
        values = index_results(results)
        tt_low = values.get((GEPS_TEMPERATURE_P50, night_rep))
        pop_night = values.get((GEPS_POP_12H, night_window_end))

        # Round the low to a whole degree to match EC's official low convention
        # (citypage lows are whole-number values); POP is an integer percent.
        self._day7_backfill = {
            "date": last_official,
            "temp_low": round(tt_low) if tt_low is not None else None,
            "pop_night": int(round(pop_night)) if pop_night is not None else None,
        }

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

    def apply_forecast_days(self, forecast_days: int) -> None:
        """Apply a forecast-range change in place, without an entry reload.

        Publishes the re-projection immediately so skeleton outlook rows
        render the instant the option is saved; the real outlook data rides
        the refresh scheduled right after. Turning the option off drops any
        stored outlook entries at once.
        """
        if forecast_days == self._forecast_days:
            return
        self._forecast_days = forecast_days
        if forecast_days <= 7:
            self._outlook = {}
        now = datetime.now(timezone.utc)
        today = dt_util.now().date()
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        self.async_set_updated_data(
            self._project_output(build_periods(today, now, local_tz))
        )
        self.hass.async_create_task(self.async_request_refresh())

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

        today = dt_util.now().date()

        # Only surface precip_windows for dates that are BOTH still in the
        # forecast range AND currently inside the GEPS coverage band (days_ahead
        # 4-6). A GEPS band is only ever (re)written for a current GEPS day; once
        # a day ages down to days_ahead 3 (RDPS-owned), _fetch_geps_day returns
        # early and never overwrites its entry, so the band would otherwise
        # linger frozen at whatever GEPS run was current when the day was last a
        # GEPS day — a stale precip band contradicting the fresher RDPS near-day
        # data. Gating the projection on is_geps_day drops those orphans.
        valid_dates = {date_str for date_str, _pt, _s, _e in periods}
        precip_windows = {
            date_str: windows
            for date_str, windows in self._precip_windows.items()
            if date_str in valid_dates
            and is_geps_day(days_ahead_for(date_str, today))
        }

        # Outlook entries (days beyond the official 7), sorted by date. Empty in
        # mode 7. Appended to the daily forecast attribute by the sensor; the HA
        # weather entity does not read these, so its forecast stays official-only.
        #
        # Refinement 1 — skeleton rows on enable: every expected outlook date
        # with no real entry yet gets a SKELETON (date + source + pending, no
        # temps/icons/sentence). Real entries win (setdefault). This makes the
        # daily attribute show the full expected date range immediately after
        # the reload that follows enabling, replaced as fetches land.
        outlook_by_date = dict(self._outlook)
        if self._forecast_days > 7:
            for date_str in outlook_dates(today, self._forecast_days):
                outlook_by_date.setdefault(date_str, {
                    "date": date_str,
                    "source": "outlook",
                    "pending": True,
                })
        outlook = [outlook_by_date[date_str] for date_str in sorted(outlook_by_date)]

        return {
            "periods": period_projection,
            "hourly": hourly_projection,
            "updated": self._last_fetch_ts,
            "days_fetched": sorted(self._completed_days),
            "precip_windows": precip_windows,
            "outlook": outlook,
            "outlook_backfill": self._day7_backfill,
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

    # ── Persistent forecast cache ────────────────────────────────────────────
    # A reboot does not make forecast data stale; only a new model run does. So
    # the coordinator persists its fetched state and, on startup, restores it
    # and lets the existing model-run-aware scheduler decide whether anything
    # needs fetching. See specs/ec_weather/persistent-forecast-cache.md.

    def _persist_cutoff(self) -> tuple[str, str]:
        """Return (store timestep cutoff, calendar-day cutoff) for pruning.

        The store keeps timesteps within the last hour (matching _do_update's
        prune); the day-keyed structures keep today and later.
        """
        now = datetime.now(timezone.utc)
        ts_cutoff = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        day_cutoff = dt_util.now().date().isoformat()
        return ts_cutoff, day_cutoff

    def _build_persist_payload(self) -> dict:
        """Build the JSON-serializable snapshot written to the store.

        Prunes past dates so the file never grows unbounded. Only fetched,
        successful state is persisted; failures were never merged into the
        store or cached, so they cannot leak in here.
        """
        ts_cutoff, day_cutoff = self._persist_cutoff()
        self._store.prune_before(ts_cutoff)
        return {
            "schema_version": STORAGE_SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "forecast_days": self._forecast_days,
            "last_model_run": self._last_model_run,
            "last_fetch_ts": self._last_fetch_ts,
            "completed_days": sorted(
                d for d in self._completed_days if d >= day_cutoff
            ),
            "timesteps": self._store.to_storage_list(),
            "precip_windows": {
                d: windows for d, windows in self._precip_windows.items()
                if d >= day_cutoff
            },
            "outlook": {
                d: entry for d, entry in self._outlook.items()
                if d >= day_cutoff
            },
            "day7_backfill": self._day7_backfill,
        }

    def _schedule_persist(self) -> None:
        """Debounced save after a successful wave / on-demand fetch.

        async_delay_save calls the builder at flush time, so the payload always
        reflects the latest merged state. A lost last-seconds save costs one
        wave, not correctness (HA flushes pending delayed saves on shutdown).
        """
        if self._persist_store is None:
            return
        self._persist_store.async_delay_save(
            self._build_persist_payload, STORAGE_SAVE_DELAY,
        )

    async def _async_persist_now(self) -> None:
        """Write the snapshot immediately (used by tests; production debounces)."""
        if self._persist_store is None:
            return
        await self._persist_store.async_save(self._build_persist_payload())

    async def async_restore(self) -> None:
        """Restore persisted forecast state before the first refresh.

        Runs in async_setup_entry before the coordinator's background refresh so
        the first _do_update sees the restored model-run stamp and the existing
        skip logic naturally avoids refetching a still-current run. Seeds
        self.data so the daily/hourly sensors show data immediately after boot.

        Restore-or-discard: a corrupt file or a payload schema mismatch is
        discarded (never migrated by guess) and the normal full fetch runs.
        """
        if self._persist_store is None:
            return
        try:
            payload = await self._persist_store.async_load()
        except Exception:  # noqa: BLE001 — any read/parse failure -> discard
            _LOGGER.info(
                "EC WEonG: persisted forecast cache unreadable, "
                "starting with a fresh fetch",
            )
            return
        if not payload:
            return  # first install — no file
        if payload.get("schema_version") != STORAGE_SCHEMA_VERSION:
            _LOGGER.info(
                "EC WEonG: persisted forecast cache schema %s != %s, "
                "discarding and refetching",
                payload.get("schema_version"), STORAGE_SCHEMA_VERSION,
            )
            return
        self._restore_from_payload(payload)

    def _restore_from_payload(self, payload: dict) -> None:
        """Seed coordinator state from a validated payload, pruning past dates.

        Honors the current config: a restored partial day stays pending (only
        the persisted _completed_days are trusted), and if extended is now off
        the persisted outlook / day-7 backfill are dropped.
        """
        ts_cutoff, day_cutoff = self._persist_cutoff()

        self._store.load_storage_list(payload.get("timesteps", []))
        self._store.prune_before(ts_cutoff)

        self._last_model_run = payload.get("last_model_run")
        self._last_fetch_ts = payload.get("last_fetch_ts")
        self._completed_days = {
            d for d in payload.get("completed_days", []) if d >= day_cutoff
        }
        self._precip_windows = {
            d: windows for d, windows in payload.get("precip_windows", {}).items()
            if d >= day_cutoff
        }

        # Restore honors the current forecast range: outlook rows and the day-7
        # backfill only exist when extended is on. If it is now off, drop them.
        if self._forecast_days > 7:
            self._outlook = {
                d: entry for d, entry in payload.get("outlook", {}).items()
                if d >= day_cutoff
            }
            self._day7_backfill = payload.get("day7_backfill")
        else:
            self._outlook = {}
            self._day7_backfill = None

        # Project once so the sensors render restored data immediately.
        now = datetime.now(timezone.utc)
        today = dt_util.now().date()
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        try:
            projected = self._project_output(build_periods(today, now, local_tz))
            self.async_set_updated_data(projected)
        except (KeyError, TypeError, ValueError):
            _LOGGER.debug("EC WEonG: could not project restored cache")

        _LOGGER.info(
            "EC WEonG: restored forecast cache — %d timesteps, %d completed days, "
            "model run %s",
            len(self._store), len(self._completed_days), self._last_model_run,
        )

    async def _do_update(self) -> dict:
        """Orchestrate per-day parallel fetch with progressive publishing.

        Results are merged into the canonical store, which preserves SkyState
        from lazy fetches and handles progressive loading safely by construction.
        No snapshot/carry-forward workarounds needed.
        """

        # Skip if data is still current and last fetch had no failures or
        # incomplete days. The mixin calls needs_refresh() before triggering,
        # but _do_update can also be called directly (polling mode), so a prior
        # degraded fetch (transient errors or partial days) must force a re-fetch
        # here too instead of skipping and leaving the holes in place.
        if (
            not self._had_transient_errors
            and not self._had_incomplete_days
            and not self.needs_refresh()
        ):
            _LOGGER.debug(
                "EC WEonG: skipping update — model run %s is current",
                self._last_model_run,
            )
            return self.data

        # Reset per-wave flags — set again during this fetch if they recur.
        self._had_transient_errors = False
        self._had_incomplete_days = False
        self._rate_limit_hits = 0
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

        # Launch all days in parallel
        await asyncio.gather(*[
            self._process_day(
                date_str, day_periods, today, now_ts, session, semaphore,
                all_periods,
            )
            for date_str, day_periods in sorted(periods_by_date.items())
        ])

        # Extended outlook wave (modes 10/14): the calendar days beyond the
        # official 7. Runs once the near-day gather is done; cached GEPS TTL
        # keeps it to one fetch per GEPS run.
        await self._fetch_outlook(today, now_ts, session, semaphore, local_tz)

        # Backfill the last official day's overnight low from the GEPS night
        # trough (refinement 2) — part of the same extended outlook wave.
        await self._fetch_day7_backfill(today, now_ts, session, semaphore, local_tz)

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
            if (
                self._had_transient_errors
                or self._had_incomplete_days
                or self._last_model_run != expected
            ):
                # Old model run, transient failures, or a partial day — retry
                # shortly instead of waiting for the next model run (F2/F4).
                self.update_interval = self._RETRY_INTERVAL
                _LOGGER.debug(
                    "EC WEonG: incomplete/degraded fetch (model run %s), "
                    "retry in %s", expected, self._RETRY_INTERVAL,
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

        # Persist the fetched state (debounced) so a reboot restores it instead
        # of refetching. Only successful, merged data is in the store — failures
        # were never cached, so they cannot leak into the file.
        self._schedule_persist()

        return result

    async def async_fetch_day_timesteps(self, date_str: str) -> None:
        """Lazy-fetch popup detail for a specific day's timesteps.

        Called by the ec_weather.fetch_day_timesteps service when the user
        opens a daily popup. SkyState is fetched for every timestep of the day
        (HRDPS days 0-2 and RDPS days 3+); POP, AirTemp and amounts are already
        in the store from the background sweep.

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

        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)

        # Extended GEPS day (4-6): the on-demand open triggers the GEPS wave, so
        # a popup works even before the background sweep has reached this day.
        # GEPS days have no WEonG timesteps (past the 84h horizon), so this runs
        # independently of the SkyState path below.
        geps_entries, geps_windows = await self._fetch_geps_day(
            date_str, day_periods, today, now_ts, session, semaphore,
        )

        # Lazy fetch: SkyState for all WEonG timesteps (POP + AirTemp + amounts
        # already in store from background sweep). SkyState is needed even
        # for wet timesteps when POP > 0 but amounts = 0.
        timestep_info = self._build_timestep_info(day_periods, today)
        sky_queries: list[tuple[str, datetime, tuple[str, str]]] = []
        for ts, pk, model in timestep_info:
            sky_queries.append((
                _weong_layer_name(_LAYER_SUFFIXES["sky_state"], model), ts, pk,
            ))

        sky_results: list = []
        if sky_queries:
            sky_results, _, _ = await self._execute_queries(
                sky_queries, now_ts, session, semaphore,
            )

        # Nothing to fetch (no WEonG timesteps and not a GEPS day) — cache empty.
        if not sky_results and not geps_entries and geps_windows is None:
            self._timestep_cache[date_str] = ({}, now_mono)
            return

        # Merge all results into the canonical store
        self._results_to_store(sky_results)
        for entry in geps_entries:
            self._store.merge(entry)
        if geps_windows is not None:
            self._precip_windows[date_str] = geps_windows

        # Completeness gate (F1 + F2): only mark the day done and write the
        # per-date cache marker when the fetch cleared the threshold. A mostly
        # failed fetch must NOT be cached, or a re-open would serve the same
        # holes without asking EC again. Its base here is the SkyState queries
        # (POP/AirTemp are already in the store) plus any GEPS entries. Decide
        # before projecting so days_fetched reflects the decision.
        sky_succeeded = sum(1 for _l, _t, _p, v in sky_results if v is not None)
        if self._is_day_complete(sky_succeeded, len(sky_results), geps_entries):
            self._completed_days.add(date_str)
            self._timestep_cache[date_str] = ({}, now_mono)
            # Evict stale cache entries — keep only dates within forecast range.
            if len(self._timestep_cache) > 7:
                oldest_key = min(
                    self._timestep_cache, key=lambda k: self._timestep_cache[k][1],
                )
                del self._timestep_cache[oldest_key]

        # Re-project and publish updated data — whatever arrived shows now.
        updated = self._project_output(all_periods)
        self.async_set_updated_data(updated)

        # Persist the on-demand day fetch (debounced) alongside background waves.
        self._schedule_persist()

        fetched_count = sum(1 for _, _, _, v in sky_results if v is not None)
        _LOGGER.debug(
            "EC WEonG: lazy-fetched %d SkyState + %d GEPS timesteps for %s",
            fetched_count, len(geps_entries), date_str,
        )


    # Sentinels returned by _query_feature_info on failures. Both are distinct
    # from None (which means "GeoMet returned no data for this timestep") and
    # neither is ever cached. _RATE_LIMITED additionally drives the wave backoff.
    _TRANSIENT_ERROR = object()
    _RATE_LIMITED = object()

    async def _query_feature_info(
        self, session: aiohttp.ClientSession, layer: str, timestep: datetime,
    ) -> float | None | object:
        """Query a single WEonG layer at one UTC timestep.

        Delegates to the standalone query_geomet_feature_info() in api_client.
        Translates the failure exceptions into sentinels that the coordinator's
        caching logic expects (never cached).

        Also captures reference_datetime from the response to track the
        current model run for freshness checks.

        Returns:
          float -- the value from GeoMet
          None -- GeoMet responded but had no data for this timestep (cacheable)
          _RATE_LIMITED -- HTTP 429, must NOT be cached; triggers backoff
          _TRANSIENT_ERROR -- other network/HTTP/parse failure, must NOT be cached
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
        except RateLimitedError:
            return self._RATE_LIMITED
        except TransientGeoMetError:
            return self._TRANSIENT_ERROR
