"""DataUpdateCoordinators for the EC Weather integration."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_LANGUAGE,
    DOMAIN,
    EC_API_BASE,
    GEOMET_BASE_URL,
    GEOMET_CRS,
    GEOMET_REQUEST_TIMEOUT,
    REQUEST_TIMEOUT,
    SCAN_INTERVAL_ALERTS,
    SCAN_INTERVAL_AQHI,
    SCAN_INTERVAL_WEATHER,
    SCAN_INTERVAL_WEONG,
    WEONG_CACHE_TTL_GDPS,
    WEONG_CACHE_TTL_HRDPS,
)

_LOGGER = logging.getLogger(__name__)


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
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _compute_wind_chill(temp: float | None, wind_speed: float | None) -> float | None:
    """Compute wind chill using the EC/Météo-Média formula.

    Returns None if conditions are outside the applicable range:
      - temp must be ≤ 20°C
      - wind_speed must be ≥ 5 km/h
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
      - Wind chill (computed from formula) when temp ≤ 20°C and wind ≥ 5 km/h
      - Humidex when temp > 20°C
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

def _get_temp_by_class(temperatures_obj: dict, cls: str, lang: str) -> float | None:
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


def _extract_period_fields(period: dict | None, lang: str, is_day: bool) -> dict:
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


def _parse_daily(items: list, lang: str, today=None) -> list[dict]:
    """Pair EC's alternating day/night periods into unified daily objects.

    EC may start with a night-only period ("Tonight") when the forecast is issued
    in the evening. We detect day vs night by whether the period has a HIGH or LOW
    temperature class, then pair correctly.

    When *today* (a date object) is provided, each item gets a ``date`` field
    (ISO string) so downstream merge code can match WEonG periods by date
    instead of counting from "now".
    """
    from datetime import timedelta

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

    result = []
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
            _LOGGER.warning(
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


# ---------------------------------------------------------------------------
# ECWeatherCoordinator — 15-minute update
# ---------------------------------------------------------------------------

class ECWeatherCoordinator(DataUpdateCoordinator):
    """Fetches city weather data from EC citypageweather-realtime API."""

    def __init__(
        self, hass: HomeAssistant, city_code: str, language: str = DEFAULT_LANGUAGE
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weather",
            update_interval=SCAN_INTERVAL_WEATHER,
        )
        self.city_code = city_code
        self.language = language

    async def _async_update_data(self) -> dict:
        lang = self.language
        url = (
            f"{EC_API_BASE}/collections/citypageweather-realtime"
            f"/items/{self.city_code}?f=json&lang={lang}&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout fetching city weather: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error fetching city weather: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Error parsing city weather JSON: {err}") from err

        props = data.get("properties") or {}
        current_raw = props.get("currentConditions") or {}
        rise_set = props.get("riseSet") or {}
        # Actual array keys are "hourlyForecasts" and "forecasts"
        hourly_items = (props.get("hourlyForecastGroup") or {}).get("hourlyForecasts") or []
        daily_items = (props.get("forecastGroup") or {}).get("forecasts") or []

        wind = current_raw.get("wind") or {}
        temp = _num(current_raw.get("temperature"), lang)
        wind_speed = _num(wind.get("speed"), lang)

        humidex_obj = current_raw.get("humidex")
        humidex = _num(humidex_obj, lang) if isinstance(humidex_obj, dict) else None

        current = {
            "temp": temp,
            "feels_like": _feels_like(temp, wind_speed, humidex),
            "humidity": _num(current_raw.get("relativeHumidity"), lang),
            "dewpoint": _num(current_raw.get("dewpoint"), lang),
            "wind_speed": wind_speed,
            "wind_gust": _num(wind.get("gust"), lang),
            "wind_direction": _str(wind.get("direction"), lang),
            "condition": _loc(current_raw.get("condition"), lang),
            "icon_code": _icon(current_raw.get("iconCode")),
        }

        try:
            hourly = _parse_hourly(hourly_items, lang)
        except Exception:
            _LOGGER.exception("EC weather: failed to parse hourly forecast")
            hourly = self.data.get("hourly", []) if self.data else []

        try:
            local_today = dt_util.now().date()
            daily = _parse_daily(daily_items, lang, today=local_today)
        except Exception:
            _LOGGER.exception("EC weather: failed to parse daily forecast")
            daily = self.data.get("daily", []) if self.data else []

        _LOGGER.debug(
            "EC weather updated: temp=%s°C feels_like=%s°C hourly=%d daily=%d",
            current["temp"],
            current["feels_like"],
            len(hourly),
            len(daily),
        )

        return {
            "current": current,
            "hourly": hourly,
            "daily": daily,
            "sunrise": _utc_to_local_hhmm(self.hass, _loc(rise_set.get("sunrise"), lang)),
            "sunset": _utc_to_local_hhmm(self.hass, _loc(rise_set.get("sunset"), lang)),
            "updated": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# ECAlertCoordinator — 10-minute update
# ---------------------------------------------------------------------------

# Priority order for determining "highest" alert type
_ALERT_TYPE_PRIORITY = ["warning", "watch", "advisory", "statement"]


class ECAlertCoordinator(DataUpdateCoordinator):
    """Fetches active weather alerts for the configured bounding box."""

    def __init__(
        self, hass: HomeAssistant, bbox: str, language: str = DEFAULT_LANGUAGE
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alerts",
            update_interval=SCAN_INTERVAL_ALERTS,
        )
        self.bbox = bbox
        self.language = language

    async def _async_update_data(self) -> dict:
        url = (
            f"{EC_API_BASE}/collections/weather-alerts/items"
            f"?bbox={self.bbox}&f=json&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout fetching alerts: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error fetching alerts: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Error parsing alerts JSON: {err}") from err

        features = data.get("features") or []
        now = datetime.now(timezone.utc)
        lang = self.language

        active = []
        for feature in features:
            props = feature.get("properties") or {}

            # Skip cancelled alerts
            status = props.get("status_en", "")
            if status == "cancelled":
                continue

            # Skip expired alerts
            expires_str = props.get("expiration_datetime")
            if expires_str:
                try:
                    expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                    if expires <= now:
                        continue
                except ValueError:
                    pass

            headline = (
                props.get(f"alert_name_{lang}")
                or props.get("alert_name_en")
                or ""
            )
            active.append({
                "headline": headline,
                "type": props.get("alert_type", ""),
                "expires": expires_str,
                "text": props.get(f"alert_text_{lang}") or props.get("alert_text_en") or "",
            })

        # Deduplicate alerts (EC API returns one per sub-zone)
        seen: set[tuple[str, str]] = set()
        unique: list[dict] = []
        for a in active:
            key = (a["headline"], a["text"])
            if key not in seen:
                seen.add(key)
                unique.append(a)
        active = unique

        # Determine the highest-priority alert type present
        highest_type = None
        for alert_type in _ALERT_TYPE_PRIORITY:
            if any(a["type"] == alert_type for a in active):
                highest_type = alert_type
                break

        _LOGGER.debug("EC alerts updated: %d active, highest=%s", len(active), highest_type)

        return {
            "alert_count": len(active),
            "alerts": active,
            "highest_type": highest_type,
        }


# ---------------------------------------------------------------------------
# AQHI risk level helper
# ---------------------------------------------------------------------------

def _aqhi_risk_level(aqhi: int | None) -> str | None:
    """Map an integer AQHI value to a risk level string."""
    if aqhi is None:
        return None
    if aqhi <= 3:
        return "low"
    if aqhi <= 6:
        return "moderate"
    if aqhi <= 10:
        return "high"
    return "very_high"


# ---------------------------------------------------------------------------
# ECAQHICoordinator — 30-minute update
# ---------------------------------------------------------------------------

class ECAQHICoordinator(DataUpdateCoordinator):
    """Fetches AQHI forecasts for the configured station.

    EC publishes hourly AQHI forecasts 4x/day. This coordinator picks
    the current-hour forecast from the most recent publication, which is
    equivalent to what EC's own AirHealth website displays.
    """

    def __init__(self, hass: HomeAssistant, aqhi_location_id: str | None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_aqhi",
            update_interval=SCAN_INTERVAL_AQHI,
        )
        self.aqhi_location_id = aqhi_location_id

    async def _async_update_data(self) -> dict:
        if not self.aqhi_location_id:
            _LOGGER.debug("EC AQHI: no AQHI station configured")
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        # Fetch upcoming forecasts — filter server-side to reduce payload
        now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        now_hour_iso = now_hour.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{EC_API_BASE}/collections/aqhi-forecasts-realtime/items"
            f"?location_id={self.aqhi_location_id}&f=json&limit=24"
            f"&sortby=forecast_datetime&skipGeometry=true"
            f"&datetime={now_hour_iso}/.."
            f"&properties=aqhi,forecast_datetime,publication_datetime"
        )
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout fetching AQHI: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error fetching AQHI: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Error parsing AQHI JSON: {err}") from err

        features = data.get("features") or []
        if not features:
            _LOGGER.debug("EC AQHI: no forecasts returned for %s", self.aqhi_location_id)
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        # Find the current-hour forecast from the most recent publication.
        # Multiple publications exist per forecast_datetime — pick the latest pub.
        candidates: list[tuple] = []

        for f in features:
            props = f.get("properties") or {}
            fdt_str = props.get("forecast_datetime", "")
            pub_str = props.get("publication_datetime", "")
            try:
                fdt = datetime.fromisoformat(fdt_str.replace("Z", "+00:00"))
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if fdt >= now_hour:
                # Sort key: latest publication first, then earliest forecast_datetime
                candidates.append((-pub.timestamp(), fdt.timestamp(), props))

        if not candidates:
            _LOGGER.debug("EC AQHI: no current-or-future forecast found")
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        candidates.sort(key=lambda x: (x[0], x[1]))
        best = candidates[0][2]

        aqhi = _safe_float(best.get("aqhi"))
        risk_level = _aqhi_risk_level(aqhi)

        _LOGGER.debug(
            "EC AQHI updated: forecast_datetime=%s aqhi=%s risk=%s",
            best.get("forecast_datetime"),
            aqhi,
            risk_level,
        )

        return {
            "aqhi": aqhi,
            "risk_level": risk_level,
            "forecast_datetime": best.get("forecast_datetime"),
        }


# ---------------------------------------------------------------------------
# ECWEonGCoordinator — 60-minute update
# ---------------------------------------------------------------------------

# WEonG layer definitions per model family
_HRDPS_PREFIX = "HRDPS-WEonG_2.5km_"
_GDPS_PREFIX = "GDPS-WEonG_15km_"

_LAYER_SUFFIXES = {
    "precip_prob": "Precip-Prob",
    "snow_amt": "SolidSnowCondAmt",
    "rain_amt": "LiquidPrecipCondAmt",
    "freezing_precip_amt": "FreezingPrecipCondAmt",
    "ice_pellet_amt": "IcePelletsCondAmt",
    "air_temp": "AirTemp",
    "sky_state": "SkyState",
}

# Temperature thresholds for selective amount queries.
# Above _WARM_THRESHOLD: only liquid rain is possible.
# Below _COLD_THRESHOLD: only snow, freezing precip, and ice pellets.
# In between: all precip types are possible (transition zone).
_WARM_THRESHOLD = 3.0  # °C — above this, skip frozen precip layers
_COLD_THRESHOLD = -3.0  # °C — below this, skip liquid rain layer

# Which amount layers to query per temperature regime
_AMT_LAYERS_WARM = ("rain_amt",)
_AMT_LAYERS_COLD = ("snow_amt", "freezing_precip_amt", "ice_pellet_amt")
_AMT_LAYERS_TRANSITION = ("rain_amt", "snow_amt", "freezing_precip_amt", "ice_pellet_amt")

# Folding: freezing precip → rain, ice pellets → snow
_FOLD_TO_RAIN = ("rain_amt", "freezing_precip_amt")
_FOLD_TO_SNOW = ("snow_amt", "ice_pellet_amt")

# Unit conversions: raw GeoMet value → mm (for rain-like) or cm (for snow-like).
# Most layers return meters, but FreezingPrecipCondAmt returns mm directly.
# rain_amt: m → mm (×1000), freezing_precip_amt: mm → mm (×1),
# snow_amt: m → cm (×100), ice_pellet_amt: m → cm (×100).
_TO_MM = {"rain_amt": 1000, "freezing_precip_amt": 1}
_TO_CM = {"snow_amt": 100, "ice_pellet_amt": 100}


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


class ECWEonGCoordinator(DataUpdateCoordinator):
    """Fetches POP and conditional precip amounts from EC GeoMet WMS.

    Queries the Weather Elements on Grid (WEonG) layers via GetFeatureInfo
    point queries, aggregates hourly/3-hourly values into day/night periods
    matching the daily forecast, and returns a dict keyed by (date_str, period_type).
    """

    def __init__(self, hass: HomeAssistant, geomet_bbox: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weong",
            update_interval=SCAN_INTERVAL_WEONG,
        )
        self.geomet_bbox = geomet_bbox
        # Cache: (layer, time_str) → (value, fetched_timestamp)
        # Model data doesn't change between runs (HRDPS every 6h, GDPS every 12h),
        # so we cache results and only re-query when the TTL expires.
        self._cache: dict[tuple[str, str], tuple[float | None, float]] = {}

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
            # Cache all results including None — model data won't appear
            # until the next run, so retrying before TTL is wasteful
            for (layer, timestep, period_key), value in zip(uncached, results):
                time_str = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
                self._cache[(layer, time_str)] = (value, now_ts)
                fetched.append((layer, timestep, period_key, value))

        return cached_results + fetched, len(cached_results), len(uncached)

    async def _async_update_data(self) -> dict:
        _LOGGER.debug("EC WEonG: starting update")
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        today = dt_util.now().date()

        # Build period definitions: list of (date_str, period_type, utc_start, utc_end)
        periods = self._build_periods(today, now)

        # Build timestep info: list of (timestep, period_key, model)
        # For day 2, we generate both HRDPS (1h) and GDPS (3h) timesteps.
        # GDPS timesteps must align to 3h boundaries from 00Z (00,03,06,...,21).
        timestep_info: list[tuple[datetime, tuple[str, str], str]] = []
        for date_str, period_type, utc_start, utc_end in periods:
            period_key = (date_str, period_type)
            days_ahead = max(0, (datetime.strptime(date_str, "%Y-%m-%d").date() - today).days)
            for model, step_h in _models_for_day(days_ahead):
                if model == "gdps":
                    # Snap start to next 3h boundary from 00Z
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

        if not timestep_info:
            _LOGGER.debug("EC WEonG: no periods to query")
            return {"periods": {}, "hourly": {}}

        session = async_get_clientsession(self.hass)
        semaphore = asyncio.Semaphore(10)

        # Phase 1: Query POP and AirTemp for all timesteps
        always_query_suffixes = ["precip_prob", "air_temp"]
        always_queries = []
        for suffix_key in always_query_suffixes:
            suffix = _LAYER_SUFFIXES[suffix_key]
            for ts, pk, model in timestep_info:
                always_queries.append((_weong_layer_name(suffix, model), ts, pk))
        always_results, always_cached, always_fetched = await self._execute_queries(
            always_queries, now_ts, session, semaphore,
        )

        # Identify wet timesteps (POP > 0) and collect temperatures
        pop_suffix = _LAYER_SUFFIXES["precip_prob"]
        temp_suffix = _LAYER_SUFFIXES["air_temp"]
        wet_timesteps: set[tuple[datetime, str]] = set()
        temp_lookup: dict[tuple[datetime, str], float] = {}  # (timestep, model) → °C
        for layer, timestep, period_key, value in always_results:
            bare = layer
            for prefix in (_HRDPS_PREFIX, _GDPS_PREFIX):
                if bare.startswith(prefix):
                    bare = bare[len(prefix):]
                    break
            bare = bare.removesuffix(".3h")
            model = "hrdps" if layer.startswith(_HRDPS_PREFIX) else "gdps"
            if bare == pop_suffix and value is not None and value > 0:
                for ts, pk, m in timestep_info:
                    if ts == timestep and pk == period_key:
                        wet_timesteps.add((timestep, m))
                        break
            elif bare == temp_suffix and value is not None:
                temp_lookup[(timestep, model)] = value

        # Phase 2: Query precip amounts for wet timesteps, layers filtered by temp
        amt_results: list[tuple[str, datetime, tuple[str, str], float | None]] = []
        amt_cached = amt_fetched = 0
        if wet_timesteps:
            amt_queries = []
            for ts, pk, model in timestep_info:
                if (ts, model) not in wet_timesteps:
                    continue
                temp = temp_lookup.get((ts, model))
                if temp is None:
                    layers = _AMT_LAYERS_TRANSITION  # safe fallback
                elif temp > _WARM_THRESHOLD:
                    layers = _AMT_LAYERS_WARM
                elif temp < _COLD_THRESHOLD:
                    layers = _AMT_LAYERS_COLD
                else:
                    layers = _AMT_LAYERS_TRANSITION
                for key in layers:
                    layer = _weong_layer_name(_LAYER_SUFFIXES[key], model)
                    amt_queries.append((layer, ts, pk))
            amt_results, amt_cached, amt_fetched = await self._execute_queries(
                amt_queries, now_ts, session, semaphore,
            )

        # Identify timesteps that actually have precip amounts > 0
        # (some wet timesteps by POP may have no actual amounts)
        amt_suffix = _LAYER_SUFFIXES["sky_state"]  # not used here, just for clarity
        has_precip_amt: set[tuple[datetime, str]] = set()
        for layer, timestep, period_key, value in amt_results:
            if value is not None and value > 0:
                model = "hrdps" if layer.startswith(_HRDPS_PREFIX) else "gdps"
                has_precip_amt.add((timestep, model))

        # Phase 3: Query SkyState for HRDPS timesteps without precip amounts
        # (used for icon derivation — dry hours or wet hours with no actual precip)
        sky_queries = []
        sky_layer = _weong_layer_name(_LAYER_SUFFIXES["sky_state"], "hrdps")
        for ts, pk, model in timestep_info:
            if model != "hrdps":
                continue
            if (ts, model) in has_precip_amt:
                continue
            sky_queries.append((sky_layer, ts, pk))
        sky_results: list[tuple[str, datetime, tuple[str, str], float | None]] = []
        sky_cached = sky_fetched = 0
        if sky_queries:
            sky_results, sky_cached, sky_fetched = await self._execute_queries(
                sky_queries, now_ts, session, semaphore,
            )

        total_cached = always_cached + amt_cached + sky_cached
        total_fetched = always_fetched + amt_fetched + sky_fetched
        all_results = always_results + amt_results + sky_results

        amt_total = amt_cached + amt_fetched
        sky_total = sky_cached + sky_fetched
        _LOGGER.debug(
            "EC WEonG: %d total queries (%d POP+temp + %d amount + %d sky), "
            "%d cached, %d fetched, %d wet timesteps across %d periods",
            len(always_queries) + amt_total + sky_total,
            len(always_queries), amt_total, sky_total,
            total_cached, total_fetched,
            len(wet_timesteps), len(periods),
        )

        try:
            return self._aggregate_results(
                all_results, periods, now, total_cached, total_fetched,
            )
        except Exception:
            _LOGGER.exception("EC WEonG: failed to aggregate results")
            if self.data:
                return self.data
            return {"periods": {}, "hourly": {}}

    def _aggregate_results(
        self,
        all_results: list,
        periods: list,
        now: datetime,
        total_cached: int,
        total_fetched: int,
    ) -> dict:
        """Aggregate raw query results into per-period output."""
        # Prefer HRDPS over GDPS for the same (period, suffix, timestep).
        # raw_values: (period_key, suffix_key, timestep) -> {model: value}
        raw_values: dict[tuple, dict[str, float | None]] = defaultdict(dict)

        # Also collect per-timestep data for hourly forecast enrichment
        # Stores both folded totals (rain_mm, snow_cm) and raw precip types
        # for icon derivation, plus sky_state for dry hours
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
            model = "hrdps" if layer.startswith(_HRDPS_PREFIX) else "gdps"
            bare = layer
            for prefix in (_HRDPS_PREFIX, _GDPS_PREFIX):
                if bare.startswith(prefix):
                    bare = bare[len(prefix):]
                    break
            bare = bare.removesuffix(".3h")
            for suffix_key, suffix in _LAYER_SUFFIXES.items():
                if bare == suffix:
                    raw_values[(period_key, suffix_key, timestep)][model] = value
                    # Fold into hourly: freezing_precip → rain, ice_pellet → snow
                    # Convert to common units (mm for rain, cm for snow) before folding
                    # Also store raw precip types and sky_state for icon derivation
                    # Only HRDPS (1h resolution) goes into hourly — skip GDPS (3h)
                    if value is not None and model == "hrdps":
                        ts_iso = timestep.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if suffix_key in _FOLD_TO_RAIN:
                            val_mm = value * _TO_MM[suffix_key]
                            existing = hourly_data[ts_iso]["rain_mm"]
                            hourly_data[ts_iso]["rain_mm"] = max(existing or 0, val_mm)
                            # Store raw type for icon derivation
                            if suffix_key == "freezing_precip_amt":
                                hourly_data[ts_iso]["freezing_precip_mm"] = val_mm
                            # rain_amt stays in folded rain_mm (no separate field needed)
                        elif suffix_key in _FOLD_TO_SNOW:
                            val_cm = value * _TO_CM[suffix_key]
                            existing = hourly_data[ts_iso]["snow_cm"]
                            hourly_data[ts_iso]["snow_cm"] = max(existing or 0, val_cm)
                            # Store raw type for icon derivation
                            if suffix_key == "ice_pellet_amt":
                                hourly_data[ts_iso]["ice_pellet_cm"] = val_cm
                            # snow_amt stays in folded snow_cm (no separate field needed)
                        elif suffix_key == "sky_state":
                            hourly_data[ts_iso]["sky_state"] = value
                        elif suffix_key == "air_temp":
                            hourly_data[ts_iso]["temp_c"] = value
                        elif suffix_key == "precip_prob":
                            hourly_data[ts_iso]["pop"] = int(round(value))
                    break

        # Resolve per-timestep values: prefer HRDPS, fall back to GDPS
        period_timesteps: dict[tuple, dict[str, list]] = defaultdict(
            lambda: {k: [] for k in _LAYER_SUFFIXES}
        )
        period_data: dict[tuple, dict[str, list]] = defaultdict(
            lambda: {k: [] for k in _LAYER_SUFFIXES}
        )
        seen_ts: dict[tuple, set] = defaultdict(set)

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

        if total_failed == len(all_results) and len(all_results) > 0:
            _LOGGER.warning(
                "EC WEonG: all %d results are None — GeoMet may be unreachable",
                len(all_results),
            )
            return {"periods": {}, "hourly": {}}

        # Prune cache entries for timesteps more than 1 hour in the past
        cutoff_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_keys = [k for k in self._cache if k[1] < cutoff_ts]
        for k in stale_keys:
            del self._cache[k]

        # Build final output — fold freezing precip → rain, ice pellets → snow
        # Per-timestep: max across contributing layers (rain vs freezing rain)
        # Per-period: sum across timesteps for total accumulation
        output: dict[tuple, dict] = {}
        for period_key in period_timesteps:
            data = period_data.get(period_key, {k: [] for k in _LAYER_SUFFIXES})
            pop_vals = data.get("precip_prob", [])
            pop = int(round(max(pop_vals))) if pop_vals else None

            ts_data = period_timesteps[period_key]
            all_times: set[datetime] = set()
            for suffix_key in ts_data:
                for t, _ in ts_data[suffix_key]:
                    all_times.add(t)
            timesteps = []
            ts_lookup: dict[tuple[str, datetime], float | None] = {}
            for suffix_key in ts_data:
                for t, v in ts_data[suffix_key]:
                    ts_lookup[(suffix_key, t)] = v

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
                timesteps.append({
                    "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pop": int(round(pop_v)) if pop_v is not None else None,
                    "snow_cm": round(snow_cm_v, 1) if snow_cm_v is not None else None,
                    "rain_mm": round(rain_mm_v, 1) if rain_mm_v is not None else None,
                    "temp_c": round(temp_v, 1) if temp_v is not None else None,
                })

            rain_amt_mm = round(rain_mm_sum, 1) if has_rain else None
            snow_amt_cm = round(snow_cm_sum, 1) if has_snow else None

            output[period_key] = {
                "pop": pop,
                "snow_amt_cm": snow_amt_cm,
                "rain_amt_mm": rain_amt_mm,
                "timesteps": timesteps,
            }

        for date_str, period_type, _, _ in periods:
            key = (date_str, period_type)
            if key not in output:
                output[key] = {
                    "pop": None,
                    "snow_amt_cm": None,
                    "rain_amt_mm": None,
                    "timesteps": [],
                }

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

        _LOGGER.debug(
            "EC WEonG updated: %d periods, %d hourly, %d cached, %d fetched, %d failed, %d cache entries",
            len(output), len(hourly_output), total_cached, total_fetched, total_failed, len(self._cache),
        )

        return {"periods": output, "hourly": hourly_output}

    def _build_periods(
        self, today, now_utc: datetime
    ) -> list[tuple[str, str, datetime, datetime]]:
        """Build a list of (date_str, 'day'|'night', utc_start, utc_end) tuples.

        Generates up to 6 days of day/night periods starting from the current
        time window. Past periods (whose end time is before now) are skipped.

        Day/night boundaries use local time (06:00/18:00) converted to UTC,
        matching EC's forecast period definitions and handling DST transitions.
        """
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        periods = []

        for day_offset in range(7):
            d = today + timedelta(days=day_offset)
            date_str = d.isoformat()
            next_d = d + timedelta(days=1)

            # Day period: 06:00–18:00 local time, converted to UTC
            day_start = datetime(d.year, d.month, d.day, 6, 0, tzinfo=local_tz).astimezone(timezone.utc)
            day_end = datetime(d.year, d.month, d.day, 18, 0, tzinfo=local_tz).astimezone(timezone.utc)

            # Night period: 18:00 local – 06:00 local next day, converted to UTC
            night_start = datetime(d.year, d.month, d.day, 18, 0, tzinfo=local_tz).astimezone(timezone.utc)
            night_end = datetime(next_d.year, next_d.month, next_d.day, 6, 0, tzinfo=local_tz).astimezone(timezone.utc)

            # Skip periods entirely in the past
            if day_end > now_utc:
                periods.append((date_str, "day", day_start, day_end))
            if night_end > now_utc:
                periods.append((date_str, "night", night_start, night_end))

        # Limit to ~12 periods (matching typical daily forecast length)
        return periods[:12]

    async def _query_feature_info(
        self, session: aiohttp.ClientSession, layer: str, timestep: datetime
    ) -> float | None:
        """Query a single WEonG layer at one UTC timestep. Returns value or None."""
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
                "EC WEonG: failed to query %s at %s: %s", layer, time_str, err
            )
            return None

        features = data.get("features") or []
        if not features:
            return None

        value = features[0].get("properties", {}).get("value")
        return _safe_float(value)
