"""Pure data transformation functions for EC Weather sensors.

These functions merge, filter, and derive data from EC and WEonG sources.
They are stateless and have no HA dependencies — easy to test directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .icon_codes import (
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
)
from .timestamp_utils import hour_from_iso


# ---------------------------------------------------------------------------
# Icon derivation from WEonG data
# ---------------------------------------------------------------------------

def _derive_icon(weong: dict, hour: int) -> tuple[int | None, str | None]:
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
    # Support both key conventions: hourly sensor uses rain_amt_mm/snow_amt_cm,
    # daily timesteps use rain_mm/snow_cm
    rain = weong.get("rain_amt_mm") or weong.get("rain_mm") or 0
    snow = weong.get("snow_amt_cm") or weong.get("snow_cm") or 0
    temp = weong.get("temp_c")

    if freezing > 0:
        return FREEZING_RAIN, "Freezing rain"
    if ice > 0:
        return ICE_PELLETS, "Ice pellets"
    if snow > 0 and rain > 0:
        return RAIN_AND_SNOW, "Rain and snow"
    if snow > 0:
        return SNOW, "Snow"
    if rain > 0 and temp is not None and temp < 0:
        return FREEZING_RAIN, "Freezing rain"
    if rain > 0:
        return RAIN, "Rain"

    # Dry — derive icon from GeoMet SkyState (0-10 cloud cover scale).
    # Thresholds: 0-2 clear, 3-4 mainly clear, 5-6 partly cloudy,
    # 7-8 mostly cloudy, 9-10 overcast.
    sky = weong.get("sky_state")
    if sky is not None:
        is_night = hour < 6 or hour >= 18
        if sky <= 2:
            return (CLEAR_NIGHT, "Clear") if is_night else (SUNNY, "Sunny")
        if sky <= 4:
            return (MAINLY_CLEAR_NIGHT, "Mainly clear") if is_night else (MAINLY_SUNNY, "Mainly sunny")
        if sky <= 6:
            return (PARTLY_CLOUDY_NIGHT, "Partly cloudy") if is_night else (PARTLY_CLOUDY_DAY, "Partly cloudy")
        if sky <= 8:
            return (MOSTLY_CLOUDY_NIGHT, "Mostly cloudy") if is_night else (MOSTLY_CLOUDY_DAY, "Mostly cloudy")
        return CLOUDY, "Cloudy"

    return None, None


def _apply_icon_fallback(entry: dict, ts_iso: str) -> None:
    """Derive icon_code from WEonG data if not already set on the entry.

    Parses the hour from the ISO timestamp and uses _derive_icon to set
    icon_code and condition from sky_state/precip data.
    """
    if entry.get("icon_code") is not None:
        return
    hour = hour_from_iso(ts_iso)
    icon_code, condition = _derive_icon(entry, hour)
    entry["icon_code"] = icon_code
    entry["condition"] = condition


# ---------------------------------------------------------------------------
# Hourly forecast merging
# ---------------------------------------------------------------------------

def _build_unified_hourly(
    ec_hourly: list[dict], weong_hourly: dict
) -> list[dict]:
    """Build a unified hourly forecast list from EC hourly + WEonG data.

    EC hourly items (0–24h) are the primary source with full data (icon, condition,
    feels_like, wind). WEonG data enriches EC items with precip amounts and extends
    the forecast to ~48h with derived icons for hours beyond EC coverage.
    """
    ec_lookup: dict[str, dict] = {}
    for item in ec_hourly:
        ts = item.get("datetime")
        if ts:
            ec_lookup[ts] = item

    all_timestamps: set[str] = set(ec_lookup.keys())
    all_timestamps.update(weong_hourly.keys())

    result = []
    for ts in sorted(all_timestamps):
        ec = ec_lookup.get(ts)
        weong = weong_hourly.get(ts)

        if ec:
            enriched = dict(ec)
            if weong:
                enriched["rain_amt_mm"] = weong.get("rain_amt_mm")
                enriched["snow_amt_cm"] = weong.get("snow_amt_cm")
                # Copy WEonG fields needed for icon derivation
                enriched["sky_state"] = weong.get("sky_state")
                enriched["freezing_precip_mm"] = weong.get("freezing_precip_mm")
                enriched["ice_pellet_cm"] = weong.get("ice_pellet_cm")
                _apply_icon_fallback(enriched, ts)
            else:
                enriched["rain_amt_mm"] = None
                enriched["snow_amt_cm"] = None
            result.append(enriched)
        elif weong:
            derived = dict(weong)
            _apply_icon_fallback(derived, ts)
            result.append({
                "datetime": ts,
                "temp": derived.get("temp_c"),
                "feels_like": None,
                "condition": derived.get("condition"),
                "icon_code": derived.get("icon_code"),
                "precip_prob": weong.get("pop"),
                "precip_amount": None,
                "precip_unit": None,
                "wind_speed": None,
                "wind_gust": None,
                "wind_direction": None,
                "rain_amt_mm": weong.get("rain_amt_mm"),
                "snow_amt_cm": weong.get("snow_amt_cm"),
            })

    return result


def _filter_past_hours(forecast: list[dict]) -> list[dict]:
    """Remove hourly items whose hour has already passed.

    Keeps the current hour (floor of now) and all future hours.
    """
    now = datetime.now(timezone.utc)
    cutoff = now.replace(minute=0, second=0, microsecond=0)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [item for item in forecast if item.get("datetime", "") >= cutoff_str]


# ---------------------------------------------------------------------------
# Daily forecast merging
# ---------------------------------------------------------------------------

def _enrich_timesteps(
    weong_data: dict | None,
    hourly_lookup: dict[str, dict],
) -> list[dict]:
    """Enrich WEonG timesteps with EC hourly data and derive missing icons.

    For timesteps within EC hourly coverage (~24h), merges in EC data
    (icon, condition, wind, feels-like). For timesteps beyond EC coverage
    or where EC has no icon, derives icon from WEonG sky_state/precip.
    """
    if not weong_data:
        return []
    raw_ts = weong_data.get("timesteps") or []
    result = []
    for ts in raw_ts:
        entry = dict(ts)
        hourly = hourly_lookup.get(ts.get("time"))
        if hourly:
            if hourly.get("temp") is not None:
                entry["temp_c"] = round(hourly["temp"], 1)
            entry["feels_like"] = hourly.get("feels_like")
            if hourly.get("icon_code") is not None:
                entry["icon_code"] = hourly["icon_code"]
                entry["condition"] = hourly.get("condition")
            entry["wind_speed"] = hourly.get("wind_speed")
            entry["wind_direction"] = hourly.get("wind_direction")
            entry["wind_gust"] = hourly.get("wind_gust")
        _apply_icon_fallback(entry, ts.get("time", ""))
        result.append(entry)
    return result


def _extract_weong_value(data: dict | None, key: str):
    """Extract a value from WEonG period data, returning None if missing."""
    return data[key] if data and data.get(key) is not None else None


def _merge_weong_into_daily(
    daily_periods: list[dict],
    weong_periods: dict,
    hourly_forecast: list[dict] | None = None,
) -> list[dict]:
    """Merge WEonG POP data and per-timestep breakdowns into daily forecast periods.

    The daily forecast contains unified day/night items (from _parse_daily):
    - Night-only item (e.g. "Tonight"): temp_high=None, temp_low set
    - Full day+night pair (e.g. "Sunday"): both temp_high and temp_low set
    - Day-only item (e.g. last "Friday"): temp_high set, temp_low=None

    The WEonG coordinator stores data keyed by (date_str, "day"|"night") tuples.
    Each daily item includes a ``date`` field (ISO string) set by _parse_daily,
    which is used to match WEonG periods directly.

    When hourly_forecast is provided, timesteps within the first 24h are enriched
    with EC hourly data (icon, condition, wind, feels-like) by matching UTC timestamps.
    """
    hourly_lookup: dict[str, dict] = {}
    if hourly_forecast:
        for h in hourly_forecast:
            ts = h.get("datetime")
            if ts:
                hourly_lookup[ts] = h

    merged = []

    for period in daily_periods:
        enriched = dict(period)
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

        # Day precip fields
        enriched["precip_prob_day"] = _extract_weong_value(day_data, "pop")
        enriched["snow_amt_cm_day"] = _extract_weong_value(day_data, "snow_amt_cm")
        enriched["rain_amt_mm_day"] = _extract_weong_value(day_data, "rain_amt_mm")

        # Night precip fields
        enriched["precip_prob_night"] = _extract_weong_value(night_data, "pop")
        enriched["snow_amt_cm_night"] = _extract_weong_value(night_data, "snow_amt_cm")
        enriched["rain_amt_mm_night"] = _extract_weong_value(night_data, "rain_amt_mm")

        # Combined max POP
        sub_periods = [s for s in [day_data, night_data] if s]
        pops = [s["pop"] for s in sub_periods if s.get("pop") is not None]
        enriched["precip_prob"] = max(pops) if pops else None

        # Per-timestep breakdowns
        enriched["timesteps_day"] = (
            _enrich_timesteps(day_data, hourly_lookup) if not is_night_only else []
        )
        enriched["timesteps_night"] = _enrich_timesteps(night_data, hourly_lookup)

        merged.append(enriched)

    return merged
