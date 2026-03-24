"""ECWEonGCoordinator and WEonG-specific code for the EC Weather integration."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_WEONG_INTERVAL,
    DOMAIN,
    GEOMET_BASE_URL,
    GEOMET_CRS,
    GEOMET_REQUEST_TIMEOUT,
    WEONG_CACHE_TTL_GDPS,
    WEONG_CACHE_TTL_HRDPS,
    WEONG_SEMAPHORE_LIMIT,
)
from .parsing import _safe_float

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WEonG layer definitions per model family
# ---------------------------------------------------------------------------

_HRDPS_PREFIX = "HRDPS-WEonG_2.5km_"
_GDPS_PREFIX = "GDPS-WEonG_15km_"

_LAYER_SUFFIXES: dict[str, str] = {
    "precip_prob": "Precip-Prob",
    "snow_amt": "SolidSnowCondAmt",
    "rain_amt": "LiquidPrecipCondAmt",
    "freezing_precip_amt": "FreezingPrecipCondAmt",
    "ice_pellet_amt": "IcePelletsCondAmt",
    "air_temp": "AirTemp",
    "sky_state": "SkyState",
}

# Temperature thresholds to reduce API calls by skipping impossible precip types.
# Snow is physically impossible above ~2°C, rain below ~-2°C.
# We use ±3°C as a safe buffer around the transition zone.
_WARM_THRESHOLD = 3.0   # °C — above this, only query rain layers
_COLD_THRESHOLD = -3.0  # °C — below this, only query snow/ice layers

# Which amount layers to query per temperature regime
_AMT_LAYERS_WARM = ("rain_amt",)
_AMT_LAYERS_COLD = ("snow_amt", "freezing_precip_amt", "ice_pellet_amt")
_AMT_LAYERS_TRANSITION = ("rain_amt", "snow_amt", "freezing_precip_amt", "ice_pellet_amt")

# Folding: freezing precip -> rain, ice pellets -> snow
_FOLD_TO_RAIN = ("rain_amt", "freezing_precip_amt")
_FOLD_TO_SNOW = ("snow_amt", "ice_pellet_amt")

# Unit conversions: raw GeoMet value -> mm (for rain-like) or cm (for snow-like).
# Most layers return meters, but FreezingPrecipCondAmt returns mm directly.
# rain_amt: m -> mm (x1000), freezing_precip_amt: mm -> mm (x1),
# snow_amt: m -> cm (x100), ice_pellet_amt: m -> cm (x100).
_TO_MM: dict[str, int] = {"rain_amt": 1000, "freezing_precip_amt": 1}
_TO_CM: dict[str, int] = {"snow_amt": 100, "ice_pellet_amt": 100}


def _weong_layer_name(suffix: str, model: str) -> str:
    """Build the full WMS layer name for the given model ('hrdps' or 'gdps')."""
    if model == "hrdps":
        return f"{_HRDPS_PREFIX}{suffix}"
    return f"{_GDPS_PREFIX}{suffix}.3h"


def _models_for_day(days_ahead: int) -> list[tuple[str, int]]:
    """Return list of (model, step_hours) to query for a given day offset.

    Days 0-1: HRDPS only (1h steps, reliable ~48h coverage).
    Day 2: Both HRDPS (1h, may partially cover) and GDPS (3h, full coverage).
           HRDPS data is preferred; GDPS fills gaps.
    Days 3+: GDPS only (3h steps).
    """
    if days_ahead <= 1:
        return [("hrdps", 1)]
    if days_ahead == 2:
        return [("hrdps", 1), ("gdps", 3)]
    return [("gdps", 3)]


# ---------------------------------------------------------------------------
# Aggregate helper functions — split from the monolithic _aggregate_results
# ---------------------------------------------------------------------------

def _bare_layer_name(layer: str) -> str:
    """Strip HRDPS/GDPS prefix and optional '.3h' suffix from a layer name.

    Returns the bare suffix portion, e.g. 'Precip-Prob' from
    'HRDPS-WEonG_2.5km_Precip-Prob' or 'GDPS-WEonG_15km_Precip-Prob.3h'.
    """
    bare = layer
    for prefix in (_HRDPS_PREFIX, _GDPS_PREFIX):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    return bare.removesuffix(".3h")


def _model_from_layer(layer: str) -> str:
    """Determine the model family from a full layer name.

    Returns 'hrdps' if the layer starts with the HRDPS prefix,
    otherwise 'gdps'.
    """
    if layer.startswith(_HRDPS_PREFIX):
        return "hrdps"
    return "gdps"


def _collect_raw_values(
    all_results: list[tuple[str, datetime, tuple[str, str], float | None]],
) -> tuple[
    dict[tuple[tuple[str, str], str, datetime], dict[str, float | None]],
    dict[str, dict[str, float | None]],
    int,
]:
    """Build raw_values dict and hourly_data from query results.

    Iterates over all (layer, timestep, period_key, value) results and:
    - Groups values by (period_key, suffix_key, timestep) -> {model: value}
    - Folds HRDPS amounts into per-timestep hourly data for card enrichment

    Returns (raw_values, hourly_data, total_failed).
    """
    raw_values: dict[
        tuple[tuple[str, str], str, datetime], dict[str, float | None]
    ] = defaultdict(dict)

    hourly_data: dict[str, dict[str, float | None]] = defaultdict(
        lambda: {
            "snow_cm": None, "rain_mm": None,
            "freezing_precip_mm": None, "ice_pellet_cm": None,
            "sky_state": None, "temp_c": None, "pop": None,
        }
    )

    total_failed = 0
    for layer, timestep, period_key, value in all_results:
        if value is None:
            total_failed += 1
        model = _model_from_layer(layer)
        bare = _bare_layer_name(layer)
        for suffix_key, suffix in _LAYER_SUFFIXES.items():
            if bare == suffix:
                raw_values[(period_key, suffix_key, timestep)][model] = value
                # Fold into hourly: only HRDPS (1h resolution) — skip GDPS (3h)
                if value is not None and model == "hrdps":
                    ts_iso = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if suffix_key in _FOLD_TO_RAIN:
                        val_mm = value * _TO_MM[suffix_key]
                        existing = hourly_data[ts_iso]["rain_mm"]
                        hourly_data[ts_iso]["rain_mm"] = max(existing or 0, val_mm)
                        if suffix_key == "freezing_precip_amt":
                            hourly_data[ts_iso]["freezing_precip_mm"] = val_mm
                    elif suffix_key in _FOLD_TO_SNOW:
                        val_cm = value * _TO_CM[suffix_key]
                        existing = hourly_data[ts_iso]["snow_cm"]
                        hourly_data[ts_iso]["snow_cm"] = max(existing or 0, val_cm)
                        if suffix_key == "ice_pellet_amt":
                            hourly_data[ts_iso]["ice_pellet_cm"] = val_cm
                    elif suffix_key == "sky_state":
                        hourly_data[ts_iso]["sky_state"] = value
                    elif suffix_key == "air_temp":
                        hourly_data[ts_iso]["temp_c"] = value
                    elif suffix_key == "precip_prob":
                        hourly_data[ts_iso]["pop"] = int(round(value))
                break

    return raw_values, hourly_data, total_failed


def _resolve_model_preference(
    raw_values: dict[
        tuple[tuple[str, str], str, datetime], dict[str, float | None]
    ],
) -> tuple[
    dict[tuple[str, str], dict[str, list[tuple[datetime, float | None]]]],
    dict[tuple[str, str], dict[str, list[float]]],
]:
    """Resolve HRDPS vs GDPS for overlapping data and deduplicate timesteps.

    For each (period_key, suffix_key, timestep), prefers HRDPS values over GDPS.
    Deduplicates so each timestep appears once per (period_key, suffix_key).

    Returns (period_timesteps, period_data) where:
    - period_timesteps: {period_key: {suffix_key: [(timestep, value), ...]}}
    - period_data: {period_key: {suffix_key: [non-None values]}}
    """
    period_timesteps: dict[tuple[str, str], dict[str, list[tuple[datetime, float | None]]]] = defaultdict(
        lambda: {k: [] for k in _LAYER_SUFFIXES}
    )
    period_data: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: {k: [] for k in _LAYER_SUFFIXES}
    )
    seen_ts: dict[tuple[tuple[str, str], str], set[datetime]] = defaultdict(set)

    for (period_key, suffix_key, timestep), models in raw_values.items():
        hrdps_val = models.get("hrdps")
        gdps_val = models.get("gdps")
        value = hrdps_val if hrdps_val is not None else gdps_val

        ts_key = (period_key, suffix_key)
        if timestep in seen_ts[ts_key]:
            continue
        seen_ts[ts_key].add(timestep)

        period_timesteps[period_key][suffix_key].append((timestep, value))
        if value is not None:
            period_data[period_key][suffix_key].append(value)

    return period_timesteps, period_data


def _build_period_output(
    period_key: tuple[str, str],
    period_timesteps: dict[tuple[str, str], dict[str, list[tuple[datetime, float | None]]]],
    period_data: dict[tuple[str, str], dict[str, list[float]]],
) -> dict:
    """Build one period's output dict with POP max, rain/snow sums, and timesteps.

    Folds freezing precip into rain and ice pellets into snow at the per-timestep
    level, then sums across timesteps for period totals.
    """
    data = period_data.get(period_key, {k: [] for k in _LAYER_SUFFIXES})
    pop_vals = data.get("precip_prob", [])
    pop = int(round(max(pop_vals))) if pop_vals else None

    ts_data = period_timesteps[period_key]
    all_times: set[datetime] = set()
    for suffix_key in ts_data:
        for t, _ in ts_data[suffix_key]:
            all_times.add(t)

    ts_lookup: dict[tuple[str, datetime], float | None] = {}
    for suffix_key in ts_data:
        for t, v in ts_data[suffix_key]:
            ts_lookup[(suffix_key, t)] = v

    timesteps: list[dict] = []
    rain_mm_sum = 0.0
    snow_cm_sum = 0.0
    has_rain = False
    has_snow = False

    for t in sorted(all_times):
        pop_v = ts_lookup.get(("precip_prob", t))
        temp_v = ts_lookup.get(("air_temp", t))
        # Fold per-timestep amounts with unit conversion
        rain_mm_components = [
            ts_lookup[(k, t)] * _TO_MM[k]
            for k in _FOLD_TO_RAIN
            if ts_lookup.get((k, t)) is not None
        ]
        snow_cm_components = [
            ts_lookup[(k, t)] * _TO_CM[k]
            for k in _FOLD_TO_SNOW
            if ts_lookup.get((k, t)) is not None
        ]
        rain_mm_v = max(rain_mm_components) if rain_mm_components else None
        snow_cm_v = max(snow_cm_components) if snow_cm_components else None
        # Accumulate for period total
        if rain_mm_v is not None and rain_mm_v > 0:
            rain_mm_sum += rain_mm_v
            has_rain = True
        if snow_cm_v is not None and snow_cm_v > 0:
            snow_cm_sum += snow_cm_v
            has_snow = True
        if pop_v is None and snow_cm_v is None and rain_mm_v is None and temp_v is None:
            continue
        sky_v = ts_lookup.get(("sky_state", t))
        timesteps.append({
            "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pop": int(round(pop_v)) if pop_v is not None else None,
            "snow_cm": round(snow_cm_v, 1) if snow_cm_v is not None else None,
            "rain_mm": round(rain_mm_v, 1) if rain_mm_v is not None else None,
            "temp_c": round(temp_v, 1) if temp_v is not None else None,
            "sky_state": round(sky_v, 1) if sky_v is not None else None,
        })

    rain_amt_mm = round(rain_mm_sum, 1) if has_rain else None
    snow_amt_cm = round(snow_cm_sum, 1) if has_snow else None

    return {
        "pop": pop,
        "snow_amt_cm": snow_amt_cm,
        "rain_amt_mm": rain_amt_mm,
        "timesteps": timesteps,
    }


def _build_hourly_output(
    hourly_data: dict[str, dict[str, float | None]],
) -> dict[str, dict]:
    """Convert per-timestep hourly_data dict to the final rounded output format.

    Each entry contains rain_amt_mm, snow_amt_cm, freezing_precip_mm,
    ice_pellet_cm, sky_state, temp_c, and pop — all rounded to 1 decimal.
    """
    hourly_output: dict[str, dict] = {}
    for ts_iso, data in hourly_data.items():
        snow_cm = data["snow_cm"]
        rain_mm = data["rain_mm"]
        freezing_mm = data["freezing_precip_mm"]
        ice_cm = data["ice_pellet_cm"]
        hourly_output[ts_iso] = {
            "snow_amt_cm": round(snow_cm, 1) if snow_cm is not None else None,
            "rain_amt_mm": round(rain_mm, 1) if rain_mm is not None else None,
            "freezing_precip_mm": round(freezing_mm, 1) if freezing_mm is not None else None,
            "ice_pellet_cm": round(ice_cm, 1) if ice_cm is not None else None,
            "sky_state": round(data["sky_state"], 1) if data["sky_state"] is not None else None,
            "temp_c": round(data["temp_c"], 1) if data["temp_c"] is not None else None,
            "pop": data["pop"],
        }
    return hourly_output


# ---------------------------------------------------------------------------
# ECWEonGCoordinator
# ---------------------------------------------------------------------------

class ECWEonGCoordinator(DataUpdateCoordinator):
    """Fetches POP and conditional precip amounts from EC GeoMet WMS.

    Queries the Weather Elements on Grid (WEonG) layers via GetFeatureInfo
    point queries, aggregates hourly/3-hourly values into day/night periods
    matching the daily forecast, and returns a dict keyed by (date_str, period_type).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        geomet_bbox: str,
        interval_minutes: int = DEFAULT_WEONG_INTERVAL,
        polling: bool = False,
    ) -> None:
        interval = timedelta(minutes=interval_minutes)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weong",
            update_interval=interval if polling else None,
        )
        self.geomet_bbox = geomet_bbox
        self._polling = polling
        self._configured_interval = interval
        self._last_refresh_ts: float | None = None
        self._had_transient_errors: bool = False
        # Cache: (layer, time_str) -> (value, fetched_timestamp)
        # Model data doesn't change between runs (HRDPS every 6h, GDPS every 12h),
        # so we cache results and only re-query when the TTL expires.
        self._cache: dict[tuple[str, str], tuple[float | None, float]] = {}
        # Lock for concurrent day merges during progressive loading
        self._merge_lock = asyncio.Lock()
        # Timestep cache for lazy popup data: {date_str: (data_dict, fetched_ts)}
        self._timestep_cache: dict[str, tuple[dict, float]] = {}

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
        self, periods: list, today,
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
                    h = utc_start.hour
                    remainder = h % 3
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
        day_periods: list,
        today,
        now_ts: float,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> list:
        """Fetch Phase 1 (POP+AirTemp) + Phase 2 (amounts) for one day's periods.

        Returns a flat list of (layer, timestep, period_key, value) result tuples.
        Does NOT fetch SkyState (Phase 3) — that's deferred to lazy popup fetch.
        """
        timestep_info = self._build_timestep_info(day_periods, today)
        if not timestep_info:
            return []

        # Phase 1: POP + AirTemp for this day
        always_queries = []
        for suffix_key in ("precip_prob", "air_temp"):
            suffix = _LAYER_SUFFIXES[suffix_key]
            for ts, pk, model in timestep_info:
                always_queries.append((_weong_layer_name(suffix, model), ts, pk))

        always_results, _, _ = await self._execute_queries(
            always_queries, now_ts, session, semaphore,
        )

        # Identify wet timesteps and temperatures from Phase 1
        pop_suffix = _LAYER_SUFFIXES["precip_prob"]
        temp_suffix = _LAYER_SUFFIXES["air_temp"]
        wet_timesteps: set[tuple[datetime, str]] = set()
        temp_lookup: dict[tuple[datetime, str], float] = {}

        for layer, timestep, period_key, value in always_results:
            bare = _bare_layer_name(layer)
            model = _model_from_layer(layer)
            if bare == pop_suffix and value is not None and value > 0:
                for ts, pk, m in timestep_info:
                    if ts == timestep and pk == period_key:
                        wet_timesteps.add((timestep, m))
                        break
            elif bare == temp_suffix and value is not None:
                temp_lookup[(timestep, model)] = value

        # Phase 2: precip amounts for wet timesteps, filtered by temperature
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

        return always_results + amt_results

    async def _async_update_data(self) -> dict:
        """Orchestrate per-day parallel fetch with progressive publishing."""

        # On-demand mode: skip if data is still fresh AND complete.
        # If the last refresh had transient errors, always re-fetch.
        if not self._polling and not self._had_transient_errors:
            now_mono = _time.monotonic()
            if (
                self.data
                and self._last_refresh_ts
                and (now_mono - self._last_refresh_ts)
                < self._configured_interval.total_seconds()
            ):
                return self.data

        # Reset transient error flag — will be set during fetch if errors occur
        self._had_transient_errors = False
        _LOGGER.debug("EC WEonG: starting update")
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        today = dt_util.now().date()

        periods = self._build_periods(today, now)
        if not periods:
            _LOGGER.debug("EC WEonG: no periods to query")
            return {"periods": {}, "hourly": {}}

        # Group periods by date for per-day parallel processing
        periods_by_date: dict[str, list] = defaultdict(list)
        for p in periods:
            periods_by_date[p[0]].append(p)

        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(WEONG_SEMAPHORE_LIMIT)

        # Collect all results from all days — progressive publishing
        all_results: list = []
        all_periods: list = list(periods)  # copy for aggregation

        async def _process_day(date_str: str, day_periods: list) -> None:
            """Fetch one day and merge results progressively."""
            day_results = await self._fetch_day(
                day_periods, today, now_ts, session, semaphore,
            )
            async with self._merge_lock:
                all_results.extend(day_results)
                try:
                    merged = self._aggregate_results(all_results, all_periods, now)
                    self.async_set_updated_data(merged)
                except (KeyError, TypeError, ValueError):
                    _LOGGER.debug(
                        "EC WEonG: partial aggregate failed "
                        "(expected during progressive load)"
                    )

        # Launch all days in parallel
        await asyncio.gather(*[
            _process_day(date_str, day_periods)
            for date_str, day_periods in sorted(periods_by_date.items())
        ])

        # Final aggregation with all results
        try:
            result = self._aggregate_results(all_results, all_periods, now)
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC WEonG: failed to aggregate results")
            if self.data:
                return self.data
            return {"periods": {}, "hourly": {}}

        _LOGGER.debug(
            "EC WEonG: update complete — %d results across %d periods",
            len(all_results), len(periods),
        )

        self._last_refresh_ts = _time.monotonic()
        return result

    async def async_fetch_day_timesteps(self, date_str: str) -> None:
        """Lazy-fetch SkyState for a specific day's timesteps (popup timeline).

        Called by the ec_weather.fetch_day_timesteps service when the user
        opens a daily popup. Queries SkyState for the requested day, merges
        into self.data, and notifies listeners so the card re-renders.

        Results are cached per-date with model-appropriate TTL.
        """

        now_mono = _time.monotonic()

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

        # Build periods for just this date
        all_periods = self._build_periods(today, now)
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

        # Identify which timesteps need SkyState (dry or zero-precip)
        # Re-use existing period data to check for precip
        existing_periods = self.data.get("periods", {})
        has_precip: set[str] = set()
        for period_type in ("day", "night"):
            period_data = existing_periods.get((date_str, period_type))
            if period_data:
                for ts in period_data.get("timesteps", []):
                    if (ts.get("rain_mm") or 0) > 0 or (ts.get("snow_cm") or 0) > 0:
                        has_precip.add(ts.get("time", ""))

        # Query SkyState for timesteps without precip
        sky_queries = []
        for ts, pk, model in timestep_info:
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            if ts_str in has_precip:
                continue
            sky_layer = _weong_layer_name(_LAYER_SUFFIXES["sky_state"], model)
            sky_queries.append((sky_layer, ts, pk))

        if not sky_queries:
            self._timestep_cache[date_str] = ({}, now_mono)
            return

        sky_results, _, _ = await self._execute_queries(
            sky_queries, now_ts, session, semaphore,
        )

        # Merge sky_state into existing period timesteps
        sky_lookup: dict[str, float | None] = {}
        for layer, timestep, period_key, value in sky_results:
            ts_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
            if value is not None:
                sky_lookup[ts_str] = value

        if sky_lookup:
            updated = dict(self.data)
            updated_periods = dict(updated.get("periods", {}))
            for period_type in ("day", "night"):
                key = (date_str, period_type)
                if key in updated_periods:
                    period = dict(updated_periods[key])
                    new_timesteps = []
                    for ts in period.get("timesteps", []):
                        ts_copy = dict(ts)
                        sky_val = sky_lookup.get(ts_copy.get("time", ""))
                        if sky_val is not None:
                            ts_copy["sky_state"] = sky_val
                        new_timesteps.append(ts_copy)
                    period["timesteps"] = new_timesteps
                    updated_periods[key] = period
            updated["periods"] = updated_periods
            self.async_set_updated_data(updated)

        self._timestep_cache[date_str] = (sky_lookup, now_mono)

        # Evict stale cache entries — keep only dates within forecast range (7 days)
        if len(self._timestep_cache) > 7:
            oldest_key = min(self._timestep_cache, key=lambda k: self._timestep_cache[k][1])
            del self._timestep_cache[oldest_key]

        _LOGGER.debug(
            "EC WEonG: fetched %d SkyState values for %s",
            len(sky_lookup), date_str,
        )

    def _aggregate_results(
        self,
        all_results: list,
        periods: list,
        now: datetime,
    ) -> dict:
        """Aggregate raw query results into per-period output.

        Orchestrates the aggregation pipeline:
        1. Collect raw values and hourly data from results
        2. Resolve HRDPS/GDPS model preference
        3. Build per-period output dicts
        4. Build hourly output
        5. Prune stale cache entries

        Returns {"periods": {(date_str, period_type): {...}, ...}, "hourly": {...}}.
        """
        raw_values, hourly_data, total_failed = _collect_raw_values(all_results)

        if total_failed == len(all_results) and len(all_results) > 0:
            _LOGGER.warning(
                "EC WEonG: all %d results are None — GeoMet may be unreachable",
                len(all_results),
            )
            return {"periods": {}, "hourly": {}}

        period_timesteps, period_data = _resolve_model_preference(raw_values)

        # Build output for each period that has data
        output: dict[tuple[str, str], dict] = {}
        for period_key in period_timesteps:
            output[period_key] = _build_period_output(
                period_key, period_timesteps, period_data,
            )

        # Fill in missing periods with empty defaults
        for date_str, period_type, _, _ in periods:
            key = (date_str, period_type)
            if key not in output:
                output[key] = {
                    "pop": None,
                    "snow_amt_cm": None,
                    "rain_amt_mm": None,
                    "timesteps": [],
                }

        hourly_output = _build_hourly_output(hourly_data)

        # Prune cache entries for timesteps more than 1 hour in the past
        cutoff_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_keys = [k for k in self._cache if k[1] < cutoff_ts]
        for k in stale_keys:
            del self._cache[k]

        _LOGGER.debug(
            "EC WEonG updated: %d periods, %d hourly, %d failed, %d cache entries",
            len(output), len(hourly_output), total_failed, len(self._cache),
        )

        return {"periods": output, "hourly": hourly_output}

    def _build_periods(
        self, today, now_utc: datetime,
    ) -> list[tuple[str, str, datetime, datetime]]:
        """Build a list of (date_str, 'day'|'night', utc_start, utc_end) tuples.

        Generates up to 6 days of day/night periods starting from the current
        time window. Past periods (whose end time is before now) are skipped.

        Day/night boundaries use local time (06:00/18:00) converted to UTC,
        matching EC's forecast period definitions and handling DST transitions.
        """
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        periods: list[tuple[str, str, datetime, datetime]] = []

        for day_offset in range(7):
            d = today + timedelta(days=day_offset)
            date_str = d.isoformat()
            next_d = d + timedelta(days=1)

            # Day period: 06:00-18:00 local time, converted to UTC
            day_start = datetime(
                d.year, d.month, d.day, 6, 0, tzinfo=local_tz,
            ).astimezone(timezone.utc)
            day_end = datetime(
                d.year, d.month, d.day, 18, 0, tzinfo=local_tz,
            ).astimezone(timezone.utc)

            # Night period: 18:00 local - 06:00 local next day, converted to UTC
            night_start = datetime(
                d.year, d.month, d.day, 18, 0, tzinfo=local_tz,
            ).astimezone(timezone.utc)
            night_end = datetime(
                next_d.year, next_d.month, next_d.day, 6, 0, tzinfo=local_tz,
            ).astimezone(timezone.utc)

            # Skip periods entirely in the past
            if day_end > now_utc:
                periods.append((date_str, "day", day_start, day_end))
            if night_end > now_utc:
                periods.append((date_str, "night", night_start, night_end))

        # Limit to ~12 periods (matching typical daily forecast length)
        return periods[:12]

    # Sentinel returned by _query_feature_info on transient errors.
    # Distinct from None (which means "GeoMet returned no data for this timestep").
    _TRANSIENT_ERROR = object()

    async def _query_feature_info(
        self, session: aiohttp.ClientSession, layer: str, timestep: datetime,
    ) -> float | None | object:
        """Query a single WEonG layer at one UTC timestep.

        Returns:
          float — the value from GeoMet
          None — GeoMet responded but had no data for this timestep
          _TRANSIENT_ERROR — network/DNS error, should NOT be cached
        """
        time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{GEOMET_BASE_URL}"
            f"?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
            f"&LAYERS={layer}&QUERY_LAYERS={layer}"
            f"&CRS={GEOMET_CRS}&BBOX={self.geomet_bbox}"
            f"&WIDTH=100&HEIGHT=100&I=50&J=50"
            f"&INFO_FORMAT=application/json&TIME={time_str}"
        )

        try:
            async with asyncio.timeout(GEOMET_REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    # GeoMet returns Content-Type: text/html even for JSON
                    data = await resp.json(content_type=None)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug(
                "EC WEonG: failed to query %s at %s: %s", layer, time_str, err,
            )
            return self._TRANSIENT_ERROR

        features = data.get("features") or []
        if not features:
            return None

        value = features[0].get("properties", {}).get("value")
        return _safe_float(value)
