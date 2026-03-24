"""EC Weather — custom integration for Environment Canada weather data."""

from __future__ import annotations

import asyncio
import logging
import pathlib

import aiohttp

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

import voluptuous as vol

from .const import (
    CONF_AQHI_INTERVAL,
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_POLLING_MODE,
    CONF_WEATHER_INTERVAL,
    CONF_WEONG_INTERVAL,
    COORDINATOR_ALERTS,
    COORDINATOR_AQHI,
    COORDINATOR_WEATHER,
    COORDINATOR_WEONG,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DEFAULT_WEONG_INTERVAL,
    DOMAIN,
    POLLING_MODE_EFFICIENT,
    POLLING_MODE_FULL,
    SERVICE_FETCH_DAY_TIMESTEPS,
)
from .coordinator import ECAlertCoordinator, ECAQHICoordinator, ECWeatherCoordinator
from .weong import ECWEonGCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["sensor", "binary_sensor", "weather"]

# ── Lovelace card registration ──────────────────────────────────────────────
CARD_RESOURCE_URL = "/ec_weather/ec-weather-card.js"
CARD_JS_FILE = pathlib.Path(__file__).parent / "www" / "ec-weather-card.js"
CARD_VERSION = "1.6.4"
CARD_VERSIONED_URL = f"{CARD_RESOURCE_URL}?v={CARD_VERSION}"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the ec-weather-card Lovelace resource."""

    # Serve the JS file from inside the component directory
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_RESOURCE_URL, str(CARD_JS_FILE), cache_headers=True)]
    )

    # Register in the Lovelace resource registry
    resources = hass.data.get("lovelace", {}).resources
    if resources is None:
        _LOGGER.warning(
            "ec_weather: Lovelace resources not available, "
            "card may not load correctly"
        )
        return True

    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    # Check if already registered; update URL if version changed
    for item in resources.async_items():
        if item["url"].startswith(CARD_RESOURCE_URL):
            if not item["url"].endswith(CARD_VERSION):
                if isinstance(resources, ResourceStorageCollection):
                    await resources.async_update_item(
                        item["id"],
                        {"res_type": "module", "url": CARD_VERSIONED_URL},
                    )
                    _LOGGER.info("ec_weather: updated card resource URL to %s", CARD_VERSIONED_URL)
            return True

    # Not registered yet — add it
    if getattr(resources, "async_create_item", None):
        await resources.async_create_item(
            {"res_type": "module", "url": CARD_VERSIONED_URL}
        )
        _LOGGER.info("ec_weather: registered Lovelace resource %s", CARD_VERSIONED_URL)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EC Weather from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    language = entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    city_code = entry.data[CONF_CITY_CODE]
    bbox = entry.data[CONF_BBOX]
    geomet_bbox = entry.data[CONF_GEOMET_BBOX]
    aqhi_location_id = entry.data.get(CONF_AQHI_LOCATION_ID)

    # Read configurable settings from config entry
    polling_mode = entry.data.get(CONF_POLLING_MODE, DEFAULT_POLLING_MODE)
    weather_interval = entry.data.get(CONF_WEATHER_INTERVAL, DEFAULT_WEATHER_INTERVAL)
    weong_interval = entry.data.get(CONF_WEONG_INTERVAL, DEFAULT_WEONG_INTERVAL)
    aqhi_interval = entry.data.get(CONF_AQHI_INTERVAL, DEFAULT_AQHI_INTERVAL)

    # Determine polling per coordinator based on mode
    weather_polls = polling_mode in (POLLING_MODE_EFFICIENT, POLLING_MODE_FULL)
    aqhi_polls = polling_mode in (POLLING_MODE_EFFICIENT, POLLING_MODE_FULL)
    weong_polls = polling_mode == POLLING_MODE_FULL

    weather_coordinator = ECWeatherCoordinator(
        hass, city_code, language=language,
        interval_minutes=weather_interval, polling=weather_polls,
    )
    alert_coordinator = ECAlertCoordinator(hass, bbox, language=language)
    aqhi_coordinator = ECAQHICoordinator(
        hass, aqhi_location_id,
        interval_minutes=aqhi_interval, polling=aqhi_polls,
    )
    weong_coordinator = ECWEonGCoordinator(
        hass, geomet_bbox,
        interval_minutes=weong_interval, polling=weong_polls,
    )

    # Fast coordinators: 1 request each, ~2s total — safe to block
    await weather_coordinator.async_config_entry_first_refresh()
    await alert_coordinator.async_config_entry_first_refresh()
    try:
        await aqhi_coordinator.async_config_entry_first_refresh()
    except (TimeoutError, aiohttp.ClientError):
        _LOGGER.debug("EC Weather: AQHI data not available, will retry")

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR_WEATHER: weather_coordinator,
        COORDINATOR_ALERTS: alert_coordinator,
        COORDINATOR_AQHI: aqhi_coordinator,
        COORDINATOR_WEONG: weong_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # WEonG makes ~100+ GeoMet requests — refresh in background.
    # Hourly/daily sections show loading state until WEonG data is ready.
    entry.async_create_background_task(
        hass, weong_coordinator.async_refresh(), "ec_weather_weong_refresh",
    )

    # Register the lazy timestep fetch service
    async def _handle_fetch_day_timesteps(call):
        date_str = call.data["date"]
        for entry_data in hass.data[DOMAIN].values():
            if COORDINATOR_WEONG in entry_data:
                coordinator = entry_data[COORDINATOR_WEONG]
                await coordinator.async_fetch_day_timesteps(date_str)
                return

    if not hass.services.has_service(DOMAIN, SERVICE_FETCH_DAY_TIMESTEPS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FETCH_DAY_TIMESTEPS,
            _handle_fetch_day_timesteps,
            schema=vol.Schema({vol.Required("date"): str}),
        )

    _LOGGER.debug("EC Weather: setup complete (language=%s)", language)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Remove service if no more entries
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_FETCH_DAY_TIMESTEPS):
            hass.services.async_remove(DOMAIN, SERVICE_FETCH_DAY_TIMESTEPS)
    return unloaded
