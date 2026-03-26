"""EC API parsing helpers and shared utilities for the EC Weather integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .utils import safe_float, safe_int

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "loc",
    "num",
    "str_val",
    "icon_val",
    "feels_like",
    "parse_hourly",
    "parse_daily",
    "utc_to_local_hhmm",
    "compute_wind_chill",
]


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

def loc(obj: Any, lang: str) -> Any:
    """Extract a localized value from a multilingual {en: ..., fr: ...} object."""
    if isinstance(obj, dict) and lang in obj:
        return obj[lang]
    return obj


def num(obj: Any, lang: str = "en") -> float | None:
    """Extract a numeric value from a measurement object {value: {en: X}}."""
    if not isinstance(obj, dict):
        return None
    raw_value = obj.get("value")
    if isinstance(raw_value, dict):
        return safe_float(raw_value.get(lang))
    return safe_float(raw_value)


def str_val(obj: Any, lang: str = "en") -> str | None:
    """Extract a string value from a measurement object {value: {en: 'SW'}}."""
    if not isinstance(obj, dict):
        return None
    raw_value = obj.get("value")
    if isinstance(raw_value, dict):
        localized_value = raw_value.get(lang)
        return str(localized_value) if localized_value is not None else None
    return str(raw_value) if raw_value is not None else None


def icon_val(obj: Any) -> int | None:
    """Extract integer code from an icon object {value: 3, format: 'gif'}."""
    if not isinstance(obj, dict):
        return None
    return safe_int(obj.get("value"))



def compute_wind_chill(temp: float | None, wind_speed: float | None) -> float | None:
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


def feels_like(
    temp: float | None, wind_speed: float | None, humidex: float | None
) -> float | None:
    """Return feels-like temperature.

    Priority:
      - Wind chill (computed from formula) when temp <= 20 C and wind >= 5 km/h
      - Humidex when temp > 20 C
      - Actual temp as fallback
    """
    wind_chill = compute_wind_chill(temp, wind_speed)
    if wind_chill is not None:
        return wind_chill
    if humidex is not None:
        return humidex
    return temp


def utc_to_local_hhmm(hass: HomeAssistant, iso_str: Any) -> str | None:
    """Convert a UTC ISO 8601 string to local HH:MM."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        parsed_dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt_util.as_local(parsed_dt).strftime("%H:%M")
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Hourly forecast parser
# ---------------------------------------------------------------------------

def parse_hourly(items: list, lang: str) -> list[dict]:
    """Parse hourly forecast items from EC API."""
    result = []
    for item in items:
        try:
            temp = num(item.get("temperature"), lang)
            wind = item.get("wind") or {}

            wind_speed = num(wind.get("speed"), lang)
            humidex_obj = item.get("humidex")
            humidex = num(humidex_obj, lang) if isinstance(humidex_obj, dict) else None

            # EC hourly uses "lop" (likelihood of precipitation), not "pop"
            lop = num(item.get("lop"), lang)

            result.append({
                "time": item.get("timestamp"),  # plain UTC ISO string
                "temp": temp,
                "feels_like": feels_like(temp, wind_speed, humidex),
                "condition": loc(item.get("condition"), lang),
                "icon_code": icon_val(item.get("iconCode")),
                "precipitation_probability": safe_int(lop),
                "wind_speed": wind_speed,
                "wind_gust": num(wind.get("gust"), lang),
                "wind_direction": str_val(wind.get("direction"), lang),
            })
        except (KeyError, TypeError, ValueError, AttributeError):
            _LOGGER.debug(
                "EC weather: skipping malformed hourly item: %s",
                item.get("timestamp", "?") if isinstance(item, dict) else "?",
            )
            continue
    return result


# ---------------------------------------------------------------------------
# Daily forecast parser
# ---------------------------------------------------------------------------

def _get_temp_by_class(
    temperatures_obj: dict, cls: str, lang: str
) -> float | None:
    """Extract temp value for a given class ('high' or 'low') from temperatures dict."""
    temp_list = (temperatures_obj or {}).get("temperature") or []
    for temp_entry in temp_list:
        if loc(temp_entry.get("class"), lang) == cls:
            temp_value = temp_entry.get("value")
            if isinstance(temp_value, dict):
                return safe_float(temp_value.get(lang))
    # Fallback: first item in list
    if temp_list:
        temp_value = temp_list[0].get("value")
        if isinstance(temp_value, dict):
            return safe_float(temp_value.get(lang))
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
        "wind_speed": num(major.get("speed"), lang),
        "wind_gust": num(major.get("gust"), lang),
        "wind_direction": str_val(major.get("direction"), lang),
    }


def _parse_humidity(period: dict, lang: str) -> int | None:
    """Extract relative humidity percentage from a forecast period."""
    rh = period.get("relativeHumidity") or {}
    val = rh.get("value")
    if isinstance(val, dict):
        return safe_int(val.get(lang))
    return safe_int(val)


def _parse_uv(period: dict, lang: str) -> dict:
    """Extract UV index and category from a forecast period (day only)."""
    uv = period.get("uv") or {}
    idx = uv.get("index")
    cat = uv.get("category")
    return {
        "uv_index": safe_int(loc(idx, lang)) if idx else None,
        "uv_category": loc(cat, lang) if cat else None,
    }


def _parse_precip_accumulation(period: dict, lang: str) -> dict:
    """Extract EC's precipitation accumulation estimate from a forecast period.

    Returns dict with amount (float), unit (str), and name (str, e.g. 'rain'/'snow').
    """
    precip = period.get("precipitation") or {}
    accum = precip.get("accumulation") or {}
    amount_obj = accum.get("amount") or {}
    return {
        "precip_accum_amount": num(amount_obj, lang),
        "precip_accum_unit": loc((amount_obj.get("units") or {}), lang),
        "precip_accum_name": loc(accum.get("name"), lang),
    }


def _parse_humidex(period: dict, lang: str) -> float | None:
    """Extract humidex value from a forecast period."""
    humidex_obj = period.get("humidex")
    if not isinstance(humidex_obj, dict):
        return None
    return num(humidex_obj, lang)


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
        "condition": loc(abbrev.get("textSummary"), lang),
        "icon_code": icon_val(abbrev.get("icon")),
        "text_summary": loc(period.get("textSummary"), lang),
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


def parse_daily(
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
        return any(loc(temp_entry.get("class"), lang) == "high" for temp_entry in temp_list)

    def _period_name(period: dict) -> str:
        return loc((period.get("period") or {}).get("textForecastName"), lang)

    def _precip_type(period: dict) -> str | None:
        precip = period.get("precipitation") or {}
        pp = precip.get("precipPeriods") or []
        return loc(pp[0].get("value"), lang) if pp else None

    result: list[dict] = []
    start = 0

    # Handle optional leading night period ("Tonight")
    if items and not _is_day(items[0]):
        try:
            night = items[0]
            temp_low = _get_temp_by_class(night.get("temperatures"), "low", lang)
            humidex = _parse_humidex(night, lang)
            night_fields = _extract_period_fields(night, lang, is_day=False)
            item = {
                "period": _period_name(night),
                "temp_high": None,
                "temp_low": temp_low,
                "feels_like_high": None,
                "feels_like_low": feels_like(temp_low, night_fields["wind_speed"], humidex),
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
                "precip_type": _precip_type(night),
            }
            if current_date is not None:
                item["date"] = current_date.isoformat()
                current_date += timedelta(days=1)
            result.append(item)
        except (KeyError, TypeError, ValueError, AttributeError):
            _LOGGER.debug("EC weather: skipping malformed leading night period")
            if current_date is not None:
                current_date += timedelta(days=1)
        start = 1

    # Pair remaining day+night periods
    remaining = items[start:]
    pairs = list(zip_longest(remaining[0::2], remaining[1::2]))
    limit = max(0, 7 - len(result))

    for day, night in pairs[:limit]:
        try:
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
                "feels_like_high": feels_like(temp_high, day_fields["wind_speed"], humidex_day),
                "feels_like_low": feels_like(temp_low, night_fields["wind_speed"], humidex_night),
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
                "precip_type": _precip_type(day),
            }
            if current_date is not None:
                item["date"] = current_date.isoformat()
                current_date += timedelta(days=1)
            result.append(item)
        except (KeyError, TypeError, ValueError, AttributeError):
            _LOGGER.debug(
                "EC weather: skipping malformed daily pair: %s",
                _period_name(day) if isinstance(day, dict) else "?",
            )
            if current_date is not None:
                current_date += timedelta(days=1)
            continue

    return result
