"""Pure data transformation functions for EC Weather sensors.

These functions merge, filter, and derive data from EC and WEonG sources.
They are stateless and have no HA dependencies — easy to test directly.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .icon_registry import (
    CLEAR_NIGHT,
    CLOUDY,
    FREEZING_RAIN,
    ICE_PELLETS,
    MAINLY_CLEAR_NIGHT,
    MAINLY_SUNNY,
    MOSTLY_CLOUDY_DAY,
    MOSTLY_CLOUDY_NIGHT,
    PARTLY_CLOUDY_DAY,
    PARTLY_CLOUDY_NIGHT,
    RAIN,
    RAIN_AND_SNOW,
    SNOW,
    SUNNY,
    condition_text,
)
from .timestamp_utils import hour_from_iso
from .timestep_store import aggregate_expected_precip

__all__ = [
    "build_unified_hourly",
    "build_daily_view",
    "filter_past_hours",
    "merge_weong_into_daily",
    "derive_icon",
    "apply_icon_fallback",
    "canonical_hourly_record",
    "HOURLY_SOURCE_MAP",
    "enrich_timesteps",
    "extract_weong_value",
    "next_hour_cutoff",
    "apply_remaining_only",
    "resolve_hourly_pop",
    "resolve_half_precip",
    "display_pop",
    "apply_display_pop",
    "POP_DISPLAY_MIN",
]


# ---------------------------------------------------------------------------
# Probability-of-precipitation display rule (backend-owned presentation)
# ---------------------------------------------------------------------------

# A POP whose ROUNDED value falls below this percent is hidden entirely. Named
# so flipping the floor (e.g. back to 5) is a one-line change here.
POP_DISPLAY_MIN = 10


def display_pop(raw: float | int | None) -> int | None:
    """Round a probability-of-precipitation UP to the next multiple of 5 for display.

    The ONE place the POP *display* rule lives. Every user-facing POP passes
    through here at the attribute-emission boundary, so the card, the weather
    entity, automations and voice assistants all read the SAME stepped number —
    the card itself is a pure printer and reimplements none of this.

    Presentation only: the raw store POPs that internal math consumes (the
    expected-amount weighting in ``aggregate_expected_precip``, the in-progress
    ``apply_remaining_only`` re-aggregation, and store-level aggregation) are
    never stepped — this runs AFTER all of that, on the emitted field alone.

    - ``None`` (and a raw 0) → ``None`` (nothing to show).
    - Otherwise round UP to the next multiple of 5 (23 → 25, 8 → 10, 56 → 60).
    - A rounded value below :data:`POP_DISPLAY_MIN` is hidden (returns ``None``),
      so raw 1-5 disappear while raw 6+ surface as ``>= 10``.
    """
    if raw is None:
        return None
    stepped = math.ceil(raw / 5) * 5
    return stepped if stepped >= POP_DISPLAY_MIN else None


def apply_display_pop(view: list[dict]) -> None:
    """Step every user-facing POP in a merged daily view IN PLACE, at emission.

    Runs after ``build_daily_view`` (merge + remaining-only + amount resolution)
    has consumed the RAW store POPs, so the expected-amount weighting and the
    in-progress re-aggregate keep their raw inputs; only the fields a human reads
    are stepped:

    - the combined / day / night daily POPs,
    - each displayed timestep's POP (the popup timeline), and
    - on GEPS outlook rows, the detail-box per-half POP and the sentence's
      dominant POP.

    ``pop_*_display`` (the >= 30 outlook LIST gate) is already stepped upstream in
    the coordinator, so it is left untouched here.
    """
    for period in view:
        for key in ("precip_prob", "precip_prob_day", "precip_prob_night"):
            if period.get(key) is not None:
                period[key] = display_pop(period[key])
        for ts_key in ("timesteps_day", "timesteps_night"):
            for timestep in period.get(ts_key) or []:
                if timestep.get("precipitation_probability") is not None:
                    timestep["precipitation_probability"] = display_pop(
                        timestep["precipitation_probability"]
                    )
        if period.get("source") == "outlook":
            for key in ("pop_day", "pop_night"):
                if period.get(key) is not None:
                    period[key] = display_pop(period[key])
            sentence = period.get("sentence")
            if isinstance(sentence, dict) and sentence.get("dominant_pop") is not None:
                # Copy so the coordinator's stored outlook entry keeps its raw
                # sentence payload (display_pop is idempotent, but never mutate
                # shared upstream state).
                period["sentence"] = {
                    **sentence,
                    "dominant_pop": display_pop(sentence["dominant_pop"]),
                }


def resolve_hourly_pop(
    weong_pop: int | None, ec_pop: int | None,
) -> int | None:
    """Resolve a single hour's probability-of-precipitation from both sources.

    This is the ONE place the per-hour POP rule lives so the hourly strip
    (``build_unified_hourly``) and the daily popup timesteps
    (``enrich_timesteps``) can never diverge for the same timestamp:

    - WEonG model pop wins whenever the WEonG value is present (not None) —
      a real 0 is a value, not "missing", so it still wins over EC ``lop``;
    - otherwise fall back to EC citypage ``lop``.

    EC citypage ``lop`` can sit flat at 0/"Nil" for a whole day while the WEonG
    model carries the real hour-by-hour probabilities beside real rain amounts,
    so preferring WEonG keeps the shown POP coherent with the shown amounts.
    """
    return weong_pop if weong_pop is not None else ec_pop


def next_hour_cutoff(now: datetime | None = None) -> str:
    """Return the ISO-UTC timestamp of the NEXT full hour after ``now``.

    Hourly surfaces are a what's-ahead instrument, so the in-progress hour is
    excluded: an item stamped at floor(now) (e.g. the 21:00 item while it is
    21:30) has already partly elapsed. The cutoff is therefore floor(now) + 1h,
    and callers keep items whose timestamp is ``>= cutoff``. Both the hourly
    strip filter (``filter_past_hours``) and the in-progress period recompute
    (``apply_remaining_only``) share this single boundary so no surface can show
    a different window start than another.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    floor_hour = now.replace(minute=0, second=0, microsecond=0)
    cutoff = floor_hour + timedelta(hours=1)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Icon derivation from WEonG data
# ---------------------------------------------------------------------------

def derive_icon(
    weong: dict, hour: int, lang: str = "en",
) -> tuple[int | None, str | None]:
    """Derive an EC-style icon_code and condition text from WEonG data.

    Priority (by severity):
      1. freezing_precip_mm > 0 → freezing rain (14)
      2. ice_pellet_cm > 0 → ice pellets (27)
      3. snow + rain both > 0 → mixed (15)
      4. snow > 0 → snow (17)
      5. rain > 0 + temp < 0 → freezing rain (14) — temp-based fallback
      6. rain > 0 → rain (12)
      7. sky_state available → cloud cover + time of day
      8. None — no data to derive from
    """
    freezing = weong.get("freezing_precip_mm") or 0
    ice = weong.get("ice_pellet_cm") or 0
    rain = weong.get("rain_mm") or 0
    snow = weong.get("snow_cm") or 0
    temp = weong.get("temp")

    if freezing > 0:
        return FREEZING_RAIN, condition_text(FREEZING_RAIN, lang)
    if ice > 0:
        return ICE_PELLETS, condition_text(ICE_PELLETS, lang)
    if snow > 0 and rain > 0:
        return RAIN_AND_SNOW, condition_text(RAIN_AND_SNOW, lang)
    if snow > 0:
        return SNOW, condition_text(SNOW, lang)
    if rain > 0 and temp is not None and temp < 0:
        return FREEZING_RAIN, condition_text(FREEZING_RAIN, lang)
    if rain > 0:
        return RAIN, condition_text(RAIN, lang)

    # Dry — derive icon from GeoMet SkyState (0-10 cloud cover scale).
    # Thresholds: 0-2 clear, 3-4 mainly clear, 5-6 partly cloudy,
    # 7-8 mostly cloudy, 9-10 overcast.
    sky = weong.get("sky_state")
    if sky is not None:
        is_night = hour < 6 or hour >= 18
        if sky <= 2:
            code = CLEAR_NIGHT if is_night else SUNNY
            return code, condition_text(code, lang)
        if sky <= 4:
            code = MAINLY_CLEAR_NIGHT if is_night else MAINLY_SUNNY
            return code, condition_text(code, lang)
        if sky <= 6:
            code = PARTLY_CLOUDY_NIGHT if is_night else PARTLY_CLOUDY_DAY
            return code, condition_text(code, lang)
        if sky <= 8:
            code = MOSTLY_CLOUDY_NIGHT if is_night else MOSTLY_CLOUDY_DAY
            return code, condition_text(code, lang)
        return CLOUDY, condition_text(CLOUDY, lang)

    return None, None


def apply_icon_fallback(entry: dict, ts_iso: str, lang: str = "en") -> None:
    """Derive icon_code from WEonG data if not already set on the entry.

    Parses the hour from the ISO timestamp and uses derive_icon to set
    icon_code and condition from sky_state/precip data.
    """
    if entry.get("icon_code") is not None:
        return
    hour = hour_from_iso(ts_iso)
    icon_code, condition = derive_icon(entry, hour, lang=lang)
    entry["icon_code"] = icon_code
    entry["condition"] = condition


# ---------------------------------------------------------------------------
# Canonical per-timestamp hourly record — the ONE source decision per field
# ---------------------------------------------------------------------------

# Authoritative field→source map for the canonical hourly record. This is the
# single documented place where each per-hour field's datasource is decided;
# ``canonical_hourly_record`` implements exactly this map, and a test asserts
# ``set(HOURLY_SOURCE_MAP) == set(record)`` so the doc cannot drift from code.
#
# Time slices: "EC-covered" = the ~24h citypage hourly horizon; "WEonG-beyond"
# = hours past it served by HRDPS/RDPS-WEonG. ``ec`` below is the parse_hourly
# item; ``weong`` is the store projection (project_hourly/project_periods).
HOURLY_SOURCE_MAP: dict[str, dict] = {
    "time": {
        "slice": "all",
        "source": "canonical timestep key (ISO UTC)",
        "fallback": None,
    },
    "temp": {
        "slice": "EC-covered → citypage; WEonG-beyond → model AirTemp",
        "source": "citypage hourly `temperature`",
        "fallback": "EC temp → WEonG AirTemp (HRDPS/RDPS-WEonG); rounded 1 dp",
    },
    "feels_like": {
        "slice": "EC-covered only",
        "source": "citypage-derived feels_like (temp + wind + humidex)",
        "fallback": "None beyond EC coverage (WEonG has no feels-like)",
    },
    "icon_code": {
        "slice": "EC-covered → citypage; else derived",
        "source": "citypage hourly `iconCode`",
        "fallback": "EC icon → derive_icon(precip type → sky_state) → None",
    },
    "condition": {
        "slice": "EC-covered → citypage; else derived",
        "source": "citypage hourly `condition` (localized)",
        "fallback": "EC condition → derive_icon condition text → None",
    },
    "precipitation_probability": {
        "slice": "all",
        "source": "WEonG model POP (Precip-Prob layer)",
        "fallback": "WEonG pop (a real 0 wins) → EC citypage `lop` "
                    "(resolve_hourly_pop)",
        # The canonical record carries the RAW POP (internal math — the
        # expected-amount weighting and remaining-only re-aggregate — reads it).
        # The value a human reads is stepped by display_pop / apply_display_pop
        # at the sensor + weather emission boundary (round UP to the next 5,
        # hidden below POP_DISPLAY_MIN); the card never re-derives it.
        "display": "raw here; display_pop at emission (round-up-5, hide < 10)",
    },
    "rain_mm": {
        "slice": "all (WEonG-owned)",
        "source": "WEonG conditional rain amount (per-hour)",
        "fallback": "None when WEonG absent for the hour",
    },
    "snow_cm": {
        "slice": "all (WEonG-owned)",
        "source": "WEonG conditional snow amount (per-hour)",
        "fallback": "None when WEonG absent for the hour",
    },
    "wind_speed": {
        "slice": "EC-covered only",
        "source": "citypage hourly `wind.speed`",
        "fallback": "None beyond EC coverage",
    },
    "wind_gust": {
        "slice": "EC-covered only",
        "source": "citypage hourly `wind.gust`",
        "fallback": "None beyond EC coverage",
    },
    "wind_direction": {
        "slice": "EC-covered only",
        "source": "citypage hourly `wind.direction`",
        "fallback": "None beyond EC coverage",
    },
}


def canonical_hourly_record(
    ts_iso: str,
    ec: dict | None,
    weong: dict | None,
    lang: str = "en",
) -> dict:
    """Build the ONE canonical per-timestamp hourly record.

    This is the single place where the datasource of every per-hour field is
    decided (see :data:`HOURLY_SOURCE_MAP`). Both the hourly strip
    (``build_unified_hourly``) and the daily popup timesteps
    (``enrich_timesteps``) derive their records from here, so the same
    timestamp yields a byte-identical record on every surface — no consumer
    makes its own source choice, and the two surfaces cannot diverge.

    ``ec`` is the EC citypage hourly item for this timestamp (parse_hourly
    shape) or None past the ~24h EC horizon. ``weong`` is the WEonG
    per-timestamp dict (store projection shape: rain_mm, snow_cm, temp,
    precipitation_probability, sky_state, freezing_precip_mm, ice_pellet_cm)
    or None where WEonG has no data. Only WEonG-owned keys are read from
    ``weong`` — its icon/condition/wind (always None from the store) are
    ignored so the ``project_hourly`` and ``project_periods`` shapes resolve
    identically.
    """
    ec = ec or {}
    weong = weong or {}

    # Temperature: EC citypage wins inside its coverage window; WEonG AirTemp
    # beyond it. One rounded (1-decimal) representation on every surface so the
    # strip and popup never carry a differently-rounded temp for the same hour.
    ec_temp = ec.get("temp")
    temp = ec_temp if ec_temp is not None else weong.get("temp")
    if temp is not None:
        temp = round(temp, 1)

    record = {
        "time": ts_iso,
        "temp": temp,
        "feels_like": ec.get("feels_like"),
        "icon_code": ec.get("icon_code"),
        "condition": ec.get("condition"),
        # Per-hour POP: WEonG model pop wins (a real 0 counts), EC lop fallback.
        "precipitation_probability": resolve_hourly_pop(
            weong.get("precipitation_probability"),
            ec.get("precipitation_probability"),
        ),
        "rain_mm": weong.get("rain_mm"),
        "snow_cm": weong.get("snow_cm"),
        "wind_speed": ec.get("wind_speed"),
        "wind_gust": ec.get("wind_gust"),
        "wind_direction": ec.get("wind_direction"),
    }

    # Icon fallback chain: when EC states no icon (beyond coverage, or a sparse
    # citypage item), derive from WEonG precip type / sky_state at this hour.
    if record["icon_code"] is None:
        icon_code, condition = derive_icon(
            {
                "freezing_precip_mm": weong.get("freezing_precip_mm"),
                "ice_pellet_cm": weong.get("ice_pellet_cm"),
                "rain_mm": weong.get("rain_mm"),
                "snow_cm": weong.get("snow_cm"),
                "temp": temp,
                "sky_state": weong.get("sky_state"),
            },
            hour_from_iso(ts_iso),
            lang=lang,
        )
        record["icon_code"] = icon_code
        record["condition"] = condition

    return record


# ---------------------------------------------------------------------------
# Hourly forecast merging
# ---------------------------------------------------------------------------

def build_unified_hourly(
    ec_hourly: list[dict], weong_hourly: dict, lang: str = "en",
) -> list[dict]:
    """Build the unified hourly strip from EC hourly + WEonG data.

    A thin window slicer over :func:`canonical_hourly_record`: it unions the EC
    and WEonG timestamps and emits one canonical record per timestamp, sorted by
    time. EC hourly items (~24h) supply icon/condition/feels_like/wind; WEonG
    supplies amounts + POP and extends the list past EC coverage with derived
    icons. Every field's source is decided in the canonical builder, so the
    strip and the daily popup timesteps cannot diverge for a shared hour.
    """
    ec_lookup: dict[str, dict] = {}
    for item in ec_hourly:
        timestamp_str = item.get("time")
        if timestamp_str:
            ec_lookup[timestamp_str] = item

    all_timestamps: set[str] = set(ec_lookup.keys())
    all_timestamps.update(weong_hourly.keys())

    return [
        canonical_hourly_record(
            timestamp_str,
            ec_lookup.get(timestamp_str),
            weong_hourly.get(timestamp_str),
            lang=lang,
        )
        for timestamp_str in sorted(all_timestamps)
    ]


def filter_past_hours(forecast: list[dict]) -> list[dict]:
    """Remove hourly items at or before the current in-progress hour.

    Hourly surfaces start at the NEXT full hour: the in-progress hour (floor of
    now) has already partly elapsed, so showing it reads as a contradiction
    against the period estimates, which only count what's ahead. Keeps items
    whose timestamp is ``>= next_hour_cutoff(now)``.
    """
    cutoff_str = next_hour_cutoff()
    return [item for item in forecast if item.get("time", "") >= cutoff_str]


# ---------------------------------------------------------------------------
# Daily forecast merging
# ---------------------------------------------------------------------------

def enrich_timesteps(
    weong_data: dict | None,
    hourly_lookup: dict[str, dict],
    lang: str = "en",
) -> list[dict]:
    """Project a period's WEonG timesteps into canonical hourly records.

    A thin period slicer over :func:`canonical_hourly_record`: for each WEonG
    timestep in the period it emits the canonical record for that timestamp,
    merging the matching EC hourly item (icon/condition/wind/feels_like) where
    EC covers the hour. Because it shares the canonical builder with
    ``build_unified_hourly``, the popup timeline and the hourly strip carry
    byte-identical records for any timestamp they both display.
    """
    if not weong_data:
        return []
    raw_timesteps = weong_data.get("timesteps") or []
    return [
        canonical_hourly_record(
            timestep.get("time", ""),
            hourly_lookup.get(timestep.get("time")),
            timestep,
            lang=lang,
        )
        for timestep in raw_timesteps
    ]


def extract_weong_value(data: dict | None, key: str):
    """Extract a value from WEonG period data, returning None if missing."""
    return data[key] if data and data.get(key) is not None else None


def extract_today_pop(merged_daily: list[dict], today_str: str) -> int | None:
    """Return today's combined probability of precipitation.

    ``merged_daily`` is the output of ``merge_weong_into_daily`` — each period
    carries a combined day/night ``precip_prob``. This picks the value for
    ``today_str`` (ISO date). Returns None when today is absent or its POP is
    null. A real 0 is preserved (not treated as missing).
    """
    for period in merged_daily:
        if period.get("date") == today_str:
            return period.get("precip_prob")
    return None


def merge_weong_into_daily(
    daily_periods: list[dict],
    weong_periods: dict,
    hourly_forecast: list[dict] | None = None,
    lang: str = "en",
    ec_updated: str | None = None,
    weong_updated: str | None = None,
    days_fetched: list[str] | None = None,
    precip_windows: dict[str, list[dict]] | None = None,
    outlook: list[dict] | None = None,
    outlook_backfill: dict | None = None,
    model_precip_estimate: bool = True,
) -> list[dict]:
    """Merge WEonG POP data and per-timestep breakdowns into daily forecast periods.

    The daily forecast contains unified day/night items (from parse_daily):
    - Night-only item (e.g. "Tonight"): temp_high=None, temp_low set
    - Full day+night pair (e.g. "Sunday"): both temp_high and temp_low set
    - Day-only item (e.g. last "Friday"): temp_high set, temp_low=None

    The WEonG coordinator stores data keyed by (date_str, "day"|"night") tuples.
    Each daily item includes a ``date`` field (ISO string) set by parse_daily,
    which is used to match WEonG periods directly.

    When hourly_forecast is provided, timesteps within the first 24h are enriched
    with EC hourly data (icon, condition, wind, feels-like) by matching UTC timestamps.

    ``model_precip_estimate`` gates exposure of the model-derived daily AMOUNT
    fields (rain_mm_day/night, snow_cm_day/night). When False (the daily
    sensor's default, driven by the CONF_MODEL_PRECIP_ESTIMATE option), those
    four fields are None so the card shows only EC-stated accumulation. POP is
    never gated — it is an EC-independent probability, always shown. The param
    defaults True here so transform-level callers keep the model amounts unless
    a consumer deliberately opts out.
    """
    fetched_dates = set(days_fetched) if days_fetched else set()
    precip_windows_by_date = precip_windows or {}

    hourly_lookup: dict[str, dict] = {}
    if hourly_forecast:
        for hourly_item in hourly_forecast:
            timestamp_str = hourly_item.get("time")
            if timestamp_str:
                hourly_lookup[timestamp_str] = hourly_item

    # Oldest-of available timestamps for each period
    timestamps = [t for t in (ec_updated, weong_updated) if t]
    updated = min(timestamps) if timestamps else None

    merged = []

    for period in daily_periods:
        enriched = dict(period)
        enriched["updated"] = updated
        has_day = period.get("temp_high") is not None
        has_night = period.get("temp_low") is not None
        is_night_only = not has_day and has_night

        date_str = period.get("date")
        if not date_str:
            merged.append(enriched)
            continue

        day_data = weong_periods.get((date_str, "day")) if has_day else None
        night_data = (
            weong_periods.get((date_str, "night"))
            if (has_night or is_night_only) else None
        )

        # Day precip fields. POP always flows through; the model-derived AMOUNT
        # fields are exposed only when the estimate option is on (else None, so
        # the card falls back to EC-stated accumulation with no card changes).
        enriched["precip_prob_day"] = extract_weong_value(day_data, "pop")
        enriched["snow_cm_day"] = (
            extract_weong_value(day_data, "snow_cm") if model_precip_estimate else None
        )
        enriched["rain_mm_day"] = (
            extract_weong_value(day_data, "rain_mm") if model_precip_estimate else None
        )

        # Night precip fields
        enriched["precip_prob_night"] = extract_weong_value(night_data, "pop")
        enriched["snow_cm_night"] = (
            extract_weong_value(night_data, "snow_cm") if model_precip_estimate else None
        )
        enriched["rain_mm_night"] = (
            extract_weong_value(night_data, "rain_mm") if model_precip_estimate else None
        )

        # Combined max POP
        sub_periods = [s for s in [day_data, night_data] if s]
        pops = [s["pop"] for s in sub_periods if s.get("pop") is not None]
        enriched["precip_prob"] = max(pops) if pops else None

        # Per-timestep breakdowns
        enriched["timesteps_day"] = (
            enrich_timesteps(day_data, hourly_lookup, lang=lang)
            if not is_night_only else []
        )
        enriched["timesteps_night"] = enrich_timesteps(
            night_data, hourly_lookup, lang=lang,
        )

        # Icons complete: true when all timestep icons have been resolved
        all_timesteps = enriched["timesteps_day"] + enriched["timesteps_night"]
        enriched["icons_complete"] = (
            len(all_timesteps) == 0 or all(
                timestep.get("icon_code") is not None for timestep in all_timesteps
            )
        )

        # Timeline tri-state: an empty timestep list is ambiguous — it looks
        # the same whether the day was fetched-and-empty (past the RDPS-WEonG
        # 84h horizon) or simply hasn't been fetched yet. days_fetched disambiguates:
        # attempted-and-empty → "unavailable", not-yet-fetched → "pending".
        if all_timesteps:
            enriched["timesteps_state"] = "loaded"
        elif date_str in fetched_dates:
            enriched["timesteps_state"] = "unavailable"
        else:
            enriched["timesteps_state"] = "pending"

        # Additive GEPS band payload — only present on extended (geps) days, so
        # the official 7-day entries keep their exact existing key set. The card
        # renders future-spanning precip vessels from these 12h windows.
        day_windows = precip_windows_by_date.get(date_str)
        if day_windows:
            enriched["precip_windows"] = day_windows

        # Refinement 2 — last official day overnight-low backfill. When extended
        # is enabled and EC hasn't published this day's night period yet, fill
        # ONLY the absent low / night POP from the GEPS night trough. Published
        # citypage values are never overwritten (guarded on None).
        if outlook_backfill and date_str == outlook_backfill.get("date"):
            if period.get("temp_low") is None and outlook_backfill.get("temp_low") is not None:
                enriched["temp_low"] = outlook_backfill["temp_low"]
            if enriched.get("precip_prob_night") is None and outlook_backfill.get("pop_night") is not None:
                enriched["precip_prob_night"] = outlook_backfill["pop_night"]

        merged.append(enriched)

    # Append GEPS outlook entries (days beyond the official 7) after the
    # official rows. Only present when the forecast_days option is > 7; the
    # official entries above keep their exact shape (backward compatible). The
    # outlook entries carry source:"outlook" and no timeline, so the card
    # renders them as muted outlook rows.
    if outlook:
        for entry in outlook:
            merged.append(dict(entry))

    return merged


# ---------------------------------------------------------------------------
# In-progress period: project only what's still ahead
# ---------------------------------------------------------------------------

_REMAINING_SUB_PERIODS = (
    ("timesteps_day", "precip_prob_day", "rain_mm_day", "snow_cm_day"),
    ("timesteps_night", "precip_prob_night", "rain_mm_night", "snow_cm_night"),
)


def apply_remaining_only(
    merged: list[dict],
    today_str: str,
    now: datetime | None = None,
    model_precip_estimate: bool = True,
) -> None:
    """Re-project the in-progress day so its totals reflect only what's ahead.

    ``project_periods`` aggregates each (date, day/night) period over its FULL
    window, so at 21:00 "Tonight" still counts the rain that fell at 18–20h.
    The card is a what's-ahead instrument: for the period that CONTAINS now, POP
    and expected amounts must count only the REMAINING timesteps — the same
    hours the hourly strip/popup can still show (window start =
    ``next_hour_cutoff``). This runs at render time (the daily sensor re-reads
    on every state read), so the value shrinks hour by hour with no refetch.

    Mutates ``merged`` in place. Only the row whose ``date`` equals
    ``today_str`` is touched:

    - Each sub-period's displayed timesteps are trimmed to what's ahead.
    - A sub-period that STRADDLES the cutoff (has both elapsed and remaining
      timesteps — i.e. the one containing now) has its POP and amounts
      re-aggregated over the remaining timesteps only.
    - A sub-period WHOLLY in the past (had timesteps, all elapsed) contributes
      NOTHING to any user-facing today value: its POP and amount fields are
      nulled (not kept), so the combined ``precip_prob``, the today-POP sensor,
      the weather entity, and the card's per-half ``dailyPrecip`` max all agree
      on the remaining-only value. (This supersedes 92d69c6's conservative
      "keep the stored total" choice, which let an already-elapsed daytime peak
      linger beside a row showing only the remaining evening.) Its displayed
      timesteps stay trimmed to empty, as before.
    - A wholly-future sub-period is untouched (nothing elapsed).

    Invariant this enforces, at any frozen clock: for TODAY's row the combined
    today POP == the card's max over the per-half POPs == the max POP over the
    row's remaining timesteps; amounts stay coherent the same way. Other days'
    rows are never entered.

    ``model_precip_estimate`` mirrors ``merge_weong_into_daily``: when False the
    recomputed rain/snow amount fields are suppressed to None (POP is never
    gated), so the gating stays coherent with the fetch-time projection.
    """
    cutoff_str = next_hour_cutoff(now)

    for period in merged:
        if period.get("date") != today_str:
            continue

        for ts_key, pop_key, rain_key, snow_key in _REMAINING_SUB_PERIODS:
            timesteps = period.get(ts_key) or []
            remaining = [ts for ts in timesteps if ts.get("time", "") >= cutoff_str]
            had_past = len(remaining) < len(timesteps)

            # Trim the displayed list to what's ahead in every case (Change 2).
            period[ts_key] = remaining

            # The straddling sub-period (elapsed AND remaining hours) is
            # re-aggregated over what's ahead. A wholly-past sub-period (had
            # elapsed timesteps, nothing remaining) contributes nothing to any
            # today value, so its POP and amounts are nulled — never left to
            # linger. A wholly-future sub-period (no past) never entered here.
            if had_past and remaining:
                pop, rain, snow = aggregate_expected_precip(
                    [
                        (
                            ts.get("precipitation_probability"),
                            ts.get("rain_mm"),
                            ts.get("snow_cm"),
                        )
                        for ts in remaining
                    ]
                )
                period[pop_key] = pop
                period[rain_key] = rain if model_precip_estimate else None
                period[snow_key] = snow if model_precip_estimate else None
            elif had_past:
                # Wholly past: excluded from every user-facing today field. POP
                # is nulled too here (unlike the never-gated live POP) because
                # the whole sub-period is behind us — there is nothing ahead to
                # state a probability for.
                period[pop_key] = None
                period[rain_key] = None
                period[snow_key] = None

        # Combined max POP is derived from the (possibly recomputed) sub-POPs.
        sub_pops = [
            period.get("precip_prob_day"),
            period.get("precip_prob_night"),
        ]
        sub_pops = [pop for pop in sub_pops if pop is not None]
        period["precip_prob"] = max(sub_pops) if sub_pops else None


# ---------------------------------------------------------------------------
# Per-half popup precip amounts — one backend decision, EC-stated first
# ---------------------------------------------------------------------------

def resolve_half_precip(
    ec_amount: float | None,
    ec_unit: str | None,
    weong_rain_mm: float | None,
    weong_snow_cm: float | None,
) -> dict:
    """Resolve ONE day/night half's display amount (rain_mm, snow_cm, estimated).

    This is the single place the popup Day/Night boxes' amounts are decided, so
    they follow the same hierarchy as the daily column (``dailyPrecip``) but at
    per-half resolution:

    - EC-stated accumulation wins when present (> 0). Its unit distinguishes
      rain (mm) from snow (cm) exactly as the column does — a ``cm`` amount is
      snow, anything else is rain — and it is a committed figure, so
      ``estimated`` is False (the box renders it bare, no tilde).
    - Otherwise the WEonG model estimate for the half (``estimated`` True, the
      box marks it with a tilde). These fields already honour the beta gate
      (None when the model-estimate option is off) and the in-progress-day
      remaining-only trim applied upstream, so this reads them as-is.

    Amounts default to 0.0 so a caller can gate rendering on ``> 0`` exactly as
    it did on the raw per-half fields.
    """
    if ec_amount is not None and ec_amount > 0:
        if ec_unit == "cm":
            return {"rain_mm": 0.0, "snow_cm": ec_amount, "estimated": False}
        return {"rain_mm": ec_amount, "snow_cm": 0.0, "estimated": False}
    return {
        "rain_mm": weong_rain_mm or 0.0,
        "snow_cm": weong_snow_cm or 0.0,
        "estimated": True,
    }


def _attach_resolved_precip(period: dict) -> None:
    """Attach ``precip_amount_day`` / ``precip_amount_night`` to a daily row.

    Skips GEPS outlook rows (``source == "outlook"``) — they carry no per-half
    EC/WEonG amount fields and render their precip from window bands, so they
    keep their exact existing key set.
    """
    if period.get("source") == "outlook":
        return
    period["precip_amount_day"] = resolve_half_precip(
        period.get("precip_accum_amount"),
        period.get("precip_accum_unit"),
        period.get("rain_mm_day"),
        period.get("snow_cm_day"),
    )
    period["precip_amount_night"] = resolve_half_precip(
        period.get("precip_accum_amount_night"),
        period.get("precip_accum_unit_night"),
        period.get("rain_mm_night"),
        period.get("snow_cm_night"),
    )


# ---------------------------------------------------------------------------
# Shared daily view — merge + remaining-only trim in lockstep
# ---------------------------------------------------------------------------

def build_daily_view(
    daily_periods: list[dict],
    weong_periods: dict,
    hourly_forecast: list[dict] | None = None,
    today_str: str | None = None,
    *,
    lang: str = "en",
    ec_updated: str | None = None,
    weong_updated: str | None = None,
    days_fetched: list[str] | None = None,
    precip_windows: dict[str, list[dict]] | None = None,
    outlook: list[dict] | None = None,
    outlook_backfill: dict | None = None,
    model_precip_estimate: bool = True,
    now: datetime | None = None,
) -> list[dict]:
    """Produce the merged + remaining-trimmed daily view in one call.

    This is the ONE place ``merge_weong_into_daily`` and ``apply_remaining_only``
    run together, so every consumer (the daily sensor, the today-POP sensor and
    the weather entity's daily forecast) gets the identical merge and the
    identical in-progress-day trim — the lockstep is structural, not a
    coincidence of three call sites happening to sequence the same two calls.

    Every parameter is threaded straight through to ``merge_weong_into_daily``
    (and ``model_precip_estimate`` / ``now`` on to ``apply_remaining_only``), so
    a caller passing only what it has today gets byte-identical output to the
    hand-written pair it replaced. ``today_str`` selects the in-progress row to
    re-project; a None/absent date simply trims nothing.
    """
    merged = merge_weong_into_daily(
        daily_periods,
        weong_periods,
        hourly_forecast,
        lang=lang,
        ec_updated=ec_updated,
        weong_updated=weong_updated,
        days_fetched=days_fetched,
        precip_windows=precip_windows,
        outlook=outlook,
        outlook_backfill=outlook_backfill,
        model_precip_estimate=model_precip_estimate,
    )
    apply_remaining_only(
        merged,
        today_str,
        now=now,
        model_precip_estimate=model_precip_estimate,
    )
    # Resolve each half's popup display amount ONCE, after the remaining-only
    # trim so today's WEonG figures reflect only the hours still ahead. The
    # popup Day/Night boxes are pure display over these fields.
    for period in merged:
        _attach_resolved_precip(period)
    return merged
