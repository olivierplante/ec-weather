"""ECWeatherCoordinator — 15-minute city weather update."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_LANGUAGE,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    EC_API_BASE,
)
from ..api_client import fetch_json_with_retry
from ..parsing import (
    feels_like,
    icon_val,
    loc,
    num,
    parse_daily,
    parse_hourly,
    str_val,
    utc_to_local_hhmm,
)
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)


class ECWeatherCoordinator(OnDemandCoordinator):
    """Fetches city weather data from EC citypageweather-realtime API."""

    def __init__(
        self,
        hass: HomeAssistant,
        city_code: str,
        language: str = DEFAULT_LANGUAGE,
        interval_minutes: int = DEFAULT_WEATHER_INTERVAL,
        polling: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weather",
            interval=timedelta(minutes=interval_minutes),
            polling=polling,
        )
        self.city_code = city_code
        self.language = language
        # Track EC API's dateTime to skip sensor update when forecast unchanged
        self._last_forecast_datetime: str | None = None

    async def _do_update(self) -> dict:
        if self.is_fresh():
            return self.data

        lang = self.language
        url = (
            f"{EC_API_BASE}/collections/citypageweather-realtime"
            f"/items/{self.city_code}?f=json&lang={lang}&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)
        data = await fetch_json_with_retry(
            session, url, label="city weather",
        )

        props = data.get("properties")
        if not isinstance(props, dict):
            _LOGGER.warning(
                "EC weather: unexpected API response structure — "
                "properties missing or not a dict"
            )
            if self.data:
                return self.data
            return {
                "current": {}, "hourly": [], "daily": [],
                "sunrise": None, "sunset": None, "updated": None,
            }

        # Skip sensor update if forecast data hasn't changed since last fetch.
        # Current conditions still get updated (observations change every ~10min),
        # but hourly/daily forecast parsing is skipped to reduce card re-renders.
        ec_last_updated = props.get("lastUpdated")
        forecast_unchanged = (
            ec_last_updated is not None
            and ec_last_updated == self._last_forecast_datetime
            and self.data is not None
        )
        if forecast_unchanged:
            _LOGGER.debug("EC weather: forecast unchanged (lastUpdated=%s), updating current only", ec_last_updated)

        current_raw = props.get("currentConditions") or {}
        rise_set = props.get("riseSet") or {}
        # Actual array keys are "hourlyForecasts" and "forecasts"
        hourly_items = (props.get("hourlyForecastGroup") or {}).get("hourlyForecasts") or []
        daily_items = (props.get("forecastGroup") or {}).get("forecasts") or []

        wind = current_raw.get("wind") or {}
        temp = num(current_raw.get("temperature"), lang)
        wind_speed = num(wind.get("speed"), lang)

        humidex_obj = current_raw.get("humidex")
        humidex = num(humidex_obj, lang) if isinstance(humidex_obj, dict) else None

        current = {
            "temp": temp,
            "feels_like": feels_like(temp, wind_speed, humidex),
            "humidity": num(current_raw.get("relativeHumidity"), lang),
            "dewpoint": num(current_raw.get("dewpoint"), lang),
            "wind_speed": wind_speed,
            "wind_gust": num(wind.get("gust"), lang),
            "wind_direction": str_val(wind.get("direction"), lang),
            "condition": loc(current_raw.get("condition"), lang),
            "icon_code": icon_val(current_raw.get("iconCode")),
        }

        if forecast_unchanged:
            # Reuse existing forecast data, only update current conditions
            hourly = self.data.get("hourly", [])
            daily = self.data.get("daily", [])
        else:
            try:
                hourly = parse_hourly(hourly_items, lang)
            except (KeyError, TypeError, ValueError):
                _LOGGER.exception("EC weather: failed to parse hourly forecast")
                hourly = self.data.get("hourly", []) if self.data else []

            try:
                local_today = dt_util.now().date()
                daily = parse_daily(daily_items, lang, today=local_today)
            except (KeyError, TypeError, ValueError):
                _LOGGER.exception("EC weather: failed to parse daily forecast")
                daily = self.data.get("daily", []) if self.data else []

            self._last_forecast_datetime = ec_last_updated

        _LOGGER.debug(
            "EC weather updated: temp=%s°C feels_like=%s°C hourly=%d daily=%d%s",
            current["temp"],
            current["feels_like"],
            len(hourly),
            len(daily),
            " (forecast reused)" if forecast_unchanged else "",
        )

        self.mark_refreshed()
        return {
            "current": current,
            "hourly": hourly,
            "daily": daily,
            "sunrise": utc_to_local_hhmm(self.hass, loc(rise_set.get("sunrise"), lang)),
            "sunset": utc_to_local_hhmm(self.hass, loc(rise_set.get("sunset"), lang)),
            "updated": datetime.now(timezone.utc).isoformat(),
        }
