"""DataUpdateCoordinators for the EC Weather integration."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    SCAN_INTERVAL_ALERTS,
    aqhi_risk_level,
)
from .parsing import (
    _fetch_json_with_retry,
    _feels_like,
    _icon,
    _loc,
    _num,
    _parse_daily,
    _parse_hourly,
    _safe_float,
    _safe_int,
    _str,
    _utc_to_local_hhmm,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ECWeatherCoordinator — 15-minute update
# ---------------------------------------------------------------------------

class ECWeatherCoordinator(DataUpdateCoordinator):
    """Fetches city weather data from EC citypageweather-realtime API."""

    def __init__(
        self,
        hass: HomeAssistant,
        city_code: str,
        language: str = DEFAULT_LANGUAGE,
        interval_minutes: int = DEFAULT_WEATHER_INTERVAL,
        polling: bool = False,
    ) -> None:
        interval = timedelta(minutes=interval_minutes)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weather",
            update_interval=interval if polling else None,
        )
        self.city_code = city_code
        self.language = language
        self._polling = polling
        self._configured_interval = interval
        self._last_refresh_ts: float | None = None

    async def _async_update_data(self) -> dict:
        # On-demand mode: skip if data is still fresh
        if not self._polling:
            now_mono = _time.monotonic()
            if (
                self.data
                and self._last_refresh_ts
                and (now_mono - self._last_refresh_ts)
                < self._configured_interval.total_seconds()
            ):
                return self.data

        lang = self.language
        url = (
            f"{EC_API_BASE}/collections/citypageweather-realtime"
            f"/items/{self.city_code}?f=json&lang={lang}&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)
        data = await _fetch_json_with_retry(
            session, url, label="city weather",
        )

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
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC weather: failed to parse hourly forecast")
            hourly = self.data.get("hourly", []) if self.data else []

        try:
            local_today = dt_util.now().date()
            daily = _parse_daily(daily_items, lang, today=local_today)
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC weather: failed to parse daily forecast")
            daily = self.data.get("daily", []) if self.data else []

        _LOGGER.debug(
            "EC weather updated: temp=%s°C feels_like=%s°C hourly=%d daily=%d",
            current["temp"],
            current["feels_like"],
            len(hourly),
            len(daily),
        )

        self._last_refresh_ts = _time.monotonic()
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
        data = await _fetch_json_with_retry(
            session, url, label="alerts",
        )

        features = data.get("features") or []
        now = datetime.now(timezone.utc)
        lang = self.language

        active: list[dict] = []
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
        highest_type: str | None = None
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
# ECAQHICoordinator — 30-minute update
# ---------------------------------------------------------------------------

class ECAQHICoordinator(DataUpdateCoordinator):
    """Fetches AQHI forecasts for the configured station.

    EC publishes hourly AQHI forecasts 4x/day. This coordinator picks
    the current-hour forecast from the most recent publication, which is
    equivalent to what EC's own AirHealth website displays.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        aqhi_location_id: str | None,
        interval_minutes: int = DEFAULT_AQHI_INTERVAL,
        polling: bool = False,
    ) -> None:
        interval = timedelta(minutes=interval_minutes)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_aqhi",
            update_interval=interval if polling else None,
        )
        self.aqhi_location_id = aqhi_location_id
        self._polling = polling
        self._configured_interval = interval
        self._last_refresh_ts: float | None = None

    async def _async_update_data(self) -> dict:
        if not self.aqhi_location_id:
            _LOGGER.debug("EC AQHI: no AQHI station configured")
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        # On-demand mode: skip if data is still fresh
        if not self._polling:
            now_mono = _time.monotonic()
            if (
                self.data
                and self._last_refresh_ts
                and (now_mono - self._last_refresh_ts)
                < self._configured_interval.total_seconds()
            ):
                return self.data

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
        data = await _fetch_json_with_retry(
            session, url, label="AQHI",
        )

        features = data.get("features") or []
        if not features:
            _LOGGER.debug("EC AQHI: no forecasts returned for %s", self.aqhi_location_id)
            return {"aqhi": None, "risk_level": None, "forecast_datetime": None}

        # Find the current-hour forecast from the most recent publication.
        # Multiple publications exist per forecast_datetime — pick the latest pub.
        candidates: list[tuple[float, float, dict]] = []

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
        risk_level = aqhi_risk_level(aqhi)

        _LOGGER.debug(
            "EC AQHI updated: forecast_datetime=%s aqhi=%s risk=%s",
            best.get("forecast_datetime"),
            aqhi,
            risk_level,
        )

        self._last_refresh_ts = _time.monotonic()
        return {
            "aqhi": aqhi,
            "risk_level": risk_level,
            "forecast_datetime": best.get("forecast_datetime"),
        }
