"""EC Weather — custom integration for Environment Canada weather data."""

from __future__ import annotations

import logging
import pathlib

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    COORDINATOR_ALERTS,
    COORDINATOR_AQHI,
    COORDINATOR_WEATHER,
    COORDINATOR_WEONG,
    DEFAULT_LANGUAGE,
    DOMAIN,
)
from .coordinator import ECAlertCoordinator, ECAQHICoordinator, ECWeatherCoordinator, ECWEonGCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "weather"]

# ── Lovelace card registration ──────────────────────────────────────────────
CARD_RESOURCE_URL = "/ec_weather/ec-weather-card.js"
CARD_JS_FILE = pathlib.Path(__file__).parent / "www" / "ec-weather-card.js"
CARD_VERSION = "1.5.1"
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

    weather_coordinator = ECWeatherCoordinator(hass, city_code, language=language)
    alert_coordinator = ECAlertCoordinator(hass, bbox, language=language)
    aqhi_coordinator = ECAQHICoordinator(hass, aqhi_location_id)
    weong_coordinator = ECWEonGCoordinator(hass, geomet_bbox)

    await weather_coordinator.async_config_entry_first_refresh()
    await alert_coordinator.async_config_entry_first_refresh()
    # AQHI may return no features if bbox has no nearby stations — don't fail setup
    try:
        await aqhi_coordinator.async_config_entry_first_refresh()
    except Exception:
        _LOGGER.debug("EC Weather: AQHI data not available, will retry")
    # WEonG (GeoMet WMS) may be temporarily unreachable — don't fail setup
    try:
        await weong_coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        _LOGGER.debug("EC Weather: WEonG first refresh failed: %s", exc)

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR_WEATHER: weather_coordinator,
        COORDINATOR_ALERTS: alert_coordinator,
        COORDINATOR_AQHI: aqhi_coordinator,
        COORDINATOR_WEONG: weong_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("EC Weather: setup complete (language=%s)", language)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
