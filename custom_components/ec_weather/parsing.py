"""EC API parsing helpers and shared utilities for the EC Weather integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    FETCH_RETRIES,
    FETCH_RETRY_DELAY,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared HTTP fetch helper with retry for transient network/DNS failures
# ---------------------------------------------------------------------------

async def _fetch_json_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
    retry_delay: int = FETCH_RETRY_DELAY,
    label: str = "data",
) -> dict:
    """Fetch JSON from a URL with retry on transient connection/DNS errors.

    Retries only on ClientConnectorError (DNS, connection refused) and
    TimeoutError. HTTP errors (4xx/5xx) and JSON parse errors are raised
    immediately since retrying won't help.
    """
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with asyncio.timeout(timeout):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as err:
            last_err = err
            if attempt < retries:
                _LOGGER.warning(
                    "EC Weather: transient error fetching %s (attempt %d/%d, "
                    "retrying in %ds): %s",
                    label, attempt, retries, retry_delay, err,
                )
                await asyncio.sleep(retry_delay)
            else:
                _LOGGER.error(
                    "EC Weather: failed to fetch %s after %d attempts: %s",
                    label, retries, err,
                )
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error fetching {label}: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Error parsing {label} JSON: {err}") from err

    raise UpdateFailed(
        f"Error fetching {label}: {last_err}"
    ) from last_err


# ---------------------------------------------------------------------------
# EC API parsing helpers
#
# The EC API wraps most values in multilingual and measurement objects:
#   Multilingual text:   {"en": "Mostly Cloudy", "fr": "Généralement nuageux"}
#   Numeric measurement: {"value": {"en": 5.9}, "units": {"en": "C"}, ...}
#   Text measurement:    {"value": {"en": "SW", "fr": "SO"}, ...}
#   Icon object:         {"value": 3, "format": "gif", "url": "..."}
#
# All helpers accept a `lang` parameter (default "en") so French is supported.
# ---------------------------------------------------------------------------

def _loc(obj: Any, lang: str) -> Any:
    """Extract a localized value from a multilingual {en: ..., fr: ...} object."""
    if isinstance(obj, dict) and lang in obj:
        return obj[lang]
    return obj


def _num(obj: Any, lang: str = "en") -> float | None:
    """Extract a numeric value from a measurement object {value: {en: X}}."""
    if not isinstance(obj, dict):
        return None
    v = obj.get("value")
    if isinstance(v, dict):
        return _safe_float(v.get(lang))
    return _safe_float(v)


def _str(obj: Any, lang: str = "en") -> str | None:
    """Extract a string value from a measurement object {value: {en: 'SW'}}."""
    if not isinstance(obj, dict):
        return None
    v = obj.get("value")
    if isinstance(v, dict):
        val = v.get(lang)
        return str(val) if val is not None else None
    return str(v) if v is not None else None


def _icon(obj: Any) -> int | None:
    """Extract integer code from an icon object {value: 3, format: 'gif'}."""
    if not isinstance(obj, dict):
        return None
    return _safe_int(obj.get("value"))


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _compute_wind_chill(temp: float | None, wind_speed: float | None) -> float | None:
    """Compute wind chill using the EC/Météo-Média formula.

    Returns None if conditions are outside the applicable range:
      - temp must be <= 20 C
      - wind_speed must be >= 5 km/h
    """
    if temp is None or wind_speed is None:
        return None
    if temp > 20 or wind_speed < 5:
        return None
    return round(
        13.12
        + 0.6215 * temp
        - 11.37 * (wind_speed ** 0.16)
        + 0.3965 * temp * (wind_speed ** 0.16),
        1,
    )


def _feels_like(
    temp: float | None, wind_speed: float | None, humidex: float | None
) -> float | None:
    """Return feels-like temperature.

    Priority:
      - Wind chill (computed from formula) when temp <= 20 C and wind >= 5 km/h
      - Humidex when temp > 20 C
      - Actual temp as fallback
    """
    wind_chill = _compute_wind_chill(temp, wind_speed)
    if wind_chill is not None:
        return wind_chill
    if humidex is not None:
        return humidex
    return temp


def _utc_to_local_hhmm(hass: HomeAssistant, iso_str: Any) -> str | None:
    """Convert a UTC ISO 8601 string to local HH:MM."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt_util.as_local(dt).strftime("%H:%M")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Hourly forecast parser
# ---------------------------------------------------------------------------

def _parse_hourly(items: list, lang: str) -> list[dict]:
    """Parse hourly forecast items from EC API."""
    result = []
    for item in items:
        temp = _num(item.get("temperature"), lang)
        wind = item.get("wind") or {}

        wind_speed = _num(wind.get("speed"), lang)
        humidex_obj = item.get("humidex")
        humidex = _num(humidex_obj, lang) if isinstance(humidex_obj, dict) else None

        # EC hourly uses "lop" (likelihood of precipitation), not "pop"
        lop = _num(item.get("lop"), lang)

        result.append({
            "datetime": item.get("timestamp"),  # plain UTC ISO string
            "temp": temp,
            "feels_like": _feels_like(temp, wind_speed, humidex),
            "condition": _loc(item.get("condition"), lang),
            "icon_code": _icon(item.get("iconCode")),
            "precip_prob": _safe_int(lop),
            "precip_amount": None,  # not provided in hourly API
            "precip_unit": None,
            "wind_speed": wind_speed,
            "wind_gust": _num(wind.get("gust"), lang),
            "wind_direction": _str(wind.get("direction"), lang),
        })
    return result


# ---------------------------------------------------------------------------
# Daily forecast parser
# ---------------------------------------------------------------------------

def _get_temp_by_class(
    temperatures_obj: dict, cls: str, lang: str
) -> float | None:
    """Extract temp value for a given class ('high' or 'low') from temperatures dict."""
    temp_list = (temperatures_obj or {}).get("temperature") or []
    for t in temp_list:
        if _loc(t.get("class"), lang) == cls:
            v = t.get("value")
            if isinstance(v, dict):
                return _safe_float(v.get(lang))
    # Fallback: first item in list
    if temp_list:
        v = temp_list[0].get("value")
        if isinstance(v, dict):
            return _safe_float(v.get(lang))
    return None


def _parse_wind(period: dict, lang: str) -> dict:
    """Extract wind data from a forecast period's winds object.

    Returns dict with speed, gust, direction (from the first/major wind period).
    """
    winds = period.get("winds") or {}
    periods = winds.get("periods") or []
    if not periods:
        return {"wind_speed": None, "wind_gust": None, "wind_direction": None}
    major = periods[0]
    return {
        "wind_speed": _num(major.get("speed"), lang),
        "wind_gust": _num(major.get("gust"), lang),
        "wind_direction": _str(major.get("direction"), lang),
    }


def _parse_humidity(period: dict, lang: str) -> int | None:
    """Extract relative humidity percentage from a forecast period."""
    rh = period.get("relativeHumidity") or {}
    val = rh.get("value")
    if isinstance(val, dict):
        return _safe_int(val.get(lang))
    return _safe_int(val)


def _parse_uv(period: dict, lang: str) -> dict:
    """Extract UV index and category from a forecast period (day only)."""
    uv = period.get("uv") or {}
    idx = uv.get("index")
    cat = uv.get("category")
    return {
        "uv_index": _safe_int(_loc(idx, lang)) if idx else None,
        "uv_category": _loc(cat, lang) if cat else None,
    }


def _parse_precip_accumulation(period: dict, lang: str) -> dict:
    """Extract EC's precipitation accumulation estimate from a forecast period.

    Returns dict with amount (float), unit (str), and name (str, e.g. 'rain'/'snow').
    """
    precip = period.get("precipitation") or {}
    accum = precip.get("accumulation") or {}
    amount_obj = accum.get("amount") or {}
    return {
        "precip_accum_amount": _num(amount_obj, lang),
        "precip_accum_unit": _loc((amount_obj.get("units") or {}), lang),
        "precip_accum_name": _loc(accum.get("name"), lang),
    }


def _parse_humidex(period: dict, lang: str) -> float | None:
    """Extract humidex value from a forecast period."""
    humidex_obj = period.get("humidex")
    if not isinstance(humidex_obj, dict):
        return None
    return _num(humidex_obj, lang)


def _extract_period_fields(
    period: dict | None, lang: str, is_day: bool
) -> dict:
    """Extract all enriched fields from a single EC forecast period.

    Returns a flat dict with all fields for one side (day or night).
    The caller prefixes/suffixes these into the unified daily object.
    """
    if period is None:
        return {
            "condition": None,
            "icon_code": None,
            "text_summary": None,
            "wind_speed": None,
            "wind_gust": None,
            "wind_direction": None,
            "humidity": None,
            "uv_index": None,
            "uv_category": None,
            "precip_accum_amount": None,
            "precip_accum_unit": None,
            "precip_accum_name": None,
        }

    abbrev = period.get("abbreviatedForecast") or {}
    wind = _parse_wind(period, lang)
    uv = _parse_uv(period, lang) if is_day else {"uv_index": None, "uv_category": None}
    accum = _parse_precip_accumulation(period, lang)

    return {
        "condition": _loc(abbrev.get("textSummary"), lang),
        "icon_code": _icon(abbrev.get("icon")),
        "text_summary": _loc(period.get("textSummary"), lang),
        "wind_speed": wind["wind_speed"],
        "wind_gust": wind["wind_gust"],
        "wind_direction": wind["wind_direction"],
        "humidity": _parse_humidity(period, lang),
        "uv_index": uv["uv_index"],
        "uv_category": uv["uv_category"],
        "precip_accum_amount": accum["precip_accum_amount"],
        "precip_accum_unit": accum["precip_accum_unit"],
        "precip_accum_name": accum["precip_accum_name"],
    }


def _parse_daily(
    items: list, lang: str, today: date | None = None
) -> list[dict]:
    """Pair EC's alternating day/night periods into unified daily objects.

    EC may start with a night-only period ("Tonight") when the forecast is issued
    in the evening. We detect day vs night by whether the period has a HIGH or LOW
    temperature class, then pair correctly.

    When *today* (a date object) is provided, each item gets a ``date`` field
    (ISO string) so downstream merge code can match WEonG periods by date
    instead of counting from "now".
    """
    current_date = today

    def _is_day(period: dict) -> bool:
        temp_list = ((period.get("temperatures") or {}).get("temperature")) or []
        return any(_loc(t.get("class"), lang) == "high" for t in temp_list)

    def _period_name(period: dict) -> str:
        return _loc((period.get("period") or {}).get("textForecastName"), lang)

    def _precip_type(period: dict) -> str | None:
        precip = period.get("precipitation") or {}
        pp = precip.get("precipPeriods") or []
        return _loc(pp[0].get("value"), lang) if pp else None

    result: list[dict] = []
    start = 0

    # Handle optional leading night period ("Tonight")
    if items and not _is_day(items[0]):
        night = items[0]
        temp_low = _get_temp_by_class(night.get("temperatures"), "low", lang)
        humidex = _parse_humidex(night, lang)
        night_fields = _extract_period_fields(night, lang, is_day=False)
        item = {
            "period": _period_name(night),
            "temp_high": None,
            "temp_low": temp_low,
            "feels_like_high": None,
            "feels_like_low": _feels_like(temp_low, night_fields["wind_speed"], humidex),
            "condition": None,
            "condition_night": night_fields["condition"],
            "icon_code": None,
            "icon_code_night": night_fields["icon_code"],
            "text_summary": None,
            "text_summary_night": night_fields["text_summary"],
            "wind_speed": None,
            "wind_gust": None,
            "wind_direction": None,
            "wind_speed_night": night_fields["wind_speed"],
            "wind_gust_night": night_fields["wind_gust"],
            "wind_direction_night": night_fields["wind_direction"],
            "humidity": None,
            "humidity_night": night_fields["humidity"],
            "uv_index": None,
            "uv_category": None,
            "precip_accum_amount": None,
            "precip_accum_unit": None,
            "precip_accum_name": None,
            "precip_accum_amount_night": night_fields["precip_accum_amount"],
            "precip_accum_unit_night": night_fields["precip_accum_unit"],
            "precip_accum_name_night": night_fields["precip_accum_name"],
            "precip_prob": None,
            "precip_amount": None,
            "precip_unit": None,
            "precip_text": None,
            "precip_type": _precip_type(night),
        }
        if current_date is not None:
            item["date"] = current_date.isoformat()
            current_date += timedelta(days=1)
        result.append(item)
        start = 1

    # Pair remaining day+night periods
    remaining = items[start:]
    pairs = list(zip_longest(remaining[0::2], remaining[1::2]))
    limit = max(0, 7 - len(result))

    for day, night in pairs[:limit]:
        if day is None:
            _LOGGER.warning("EC daily forecast: unexpected None day period, skipping")
            continue
        if night is None:
            _LOGGER.debug(
                "EC daily forecast: no night period paired with '%s'",
                _period_name(day),
            )

        temp_high = _get_temp_by_class(day.get("temperatures"), "high", lang)
        temp_low = _get_temp_by_class((night or {}).get("temperatures"), "low", lang)
        humidex_day = _parse_humidex(day, lang)
        humidex_night = _parse_humidex(night, lang) if night else None

        day_fields = _extract_period_fields(day, lang, is_day=True)
        night_fields = _extract_period_fields(night, lang, is_day=False)

        item = {
            "period": _period_name(day),
            "temp_high": temp_high,
            "temp_low": temp_low,
            "feels_like_high": _feels_like(temp_high, day_fields["wind_speed"], humidex_day),
            "feels_like_low": _feels_like(temp_low, night_fields["wind_speed"], humidex_night),
            "condition": day_fields["condition"],
            "condition_night": night_fields["condition"],
            "icon_code": day_fields["icon_code"],
            "icon_code_night": night_fields["icon_code"],
            "text_summary": day_fields["text_summary"],
            "text_summary_night": night_fields["text_summary"],
            "wind_speed": day_fields["wind_speed"],
            "wind_gust": day_fields["wind_gust"],
            "wind_direction": day_fields["wind_direction"],
            "wind_speed_night": night_fields["wind_speed"],
            "wind_gust_night": night_fields["wind_gust"],
            "wind_direction_night": night_fields["wind_direction"],
            "humidity": day_fields["humidity"],
            "humidity_night": night_fields["humidity"],
            "uv_index": day_fields["uv_index"],
            "uv_category": day_fields["uv_category"],
            "precip_accum_amount": day_fields["precip_accum_amount"],
            "precip_accum_unit": day_fields["precip_accum_unit"],
            "precip_accum_name": day_fields["precip_accum_name"],
            "precip_accum_amount_night": night_fields["precip_accum_amount"],
            "precip_accum_unit_night": night_fields["precip_accum_unit"],
            "precip_accum_name_night": night_fields["precip_accum_name"],
            "precip_prob": None,
            "precip_amount": None,
            "precip_unit": None,
            "precip_text": None,
            "precip_type": _precip_type(day),
        }
        if current_date is not None:
            item["date"] = current_date.isoformat()
            current_date += timedelta(days=1)
        result.append(item)

    return result
