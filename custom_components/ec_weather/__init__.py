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
    CONF_EXTENDED_FORECAST,
    CONF_FORECAST_DAYS,
    EXTENDED_FORECAST_DAYS,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_POLLING_MODE,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
    CONF_WEATHER_INTERVAL,
    COORDINATOR_WEONG,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_LANGUAGE,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    POLLING_MODE_EFFICIENT,
    POLLING_MODE_FULL,
    SERVICE_FETCH_DAY_TIMESTEPS,
)
from .coordinator import ECAlertCoordinator, ECAQHICoordinator, ECWeatherCoordinator
from .coordinator import ECWEonGCoordinator, ECClimateCoordinator
from .models import ECWeatherData

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def validate_bbox(bbox: str | None) -> bool:
    """Return True if bbox is formatted as 4 comma-separated floats."""
    if not bbox or not isinstance(bbox, str):
        return False
    parts = bbox.split(",")
    if len(parts) != 4:
        return False
    try:
        for p in parts:
            float(p.strip())
    except (ValueError, TypeError):
        return False
    return True


PLATFORMS = ["sensor", "binary_sensor", "weather"]

# ── Lovelace card registration ──────────────────────────────────────────────
CARD_RESOURCE_URL = "/ec_weather/ec-weather-card.js"
CARD_JS_FILE = pathlib.Path(__file__).parent / "www" / "ec-weather-card.js"
# CARD_VERSION is a content hash for browser cache busting (?v=abc123).
# Computed from the JS file contents — changes automatically when the file changes.
import hashlib
CARD_VERSION = hashlib.md5(CARD_JS_FILE.read_bytes()).hexdigest()[:8]
CARD_VERSIONED_URL = f"{CARD_RESOURCE_URL}?v={CARD_VERSION}"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the ec-weather-card Lovelace resource."""

    # Serve the JS file from inside the component directory. The screenshots
    # dir is served too when present (docs rendered inside HA reference it),
    # but HACS installs don't ship it (.hacsignore) — guard, or setup breaks
    # for every HACS user.
    static_paths = [
        StaticPathConfig(CARD_RESOURCE_URL, str(CARD_JS_FILE), cache_headers=True)
    ]
    screenshots_dir = CARD_JS_FILE.parent.parent / "screenshots"
    if screenshots_dir.is_dir():
        static_paths.append(
            StaticPathConfig(
                "/ec_weather/screenshots", str(screenshots_dir), cache_headers=True
            )
        )
    await hass.http.async_register_static_paths(static_paths)

    # Register in the Lovelace resource registry
    resources = hass.data.get("lovelace", {}).resources
    if resources is None:
        _LOGGER.warning(
            "ec_weather: Lovelace resources not available, "
            "card may not load correctly"
        )
        return True

    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
    except AttributeError:
        # HA internals may change; log and continue
        _LOGGER.debug("ec_weather: could not check resource load state")
        try:
            await resources.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("ec_weather: failed to load Lovelace resources", exc_info=True)

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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries from older versions."""
    if entry.version == 1:
        _LOGGER.debug("Migrating EC Weather config entry from version 1 to 2")
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        for key in (CONF_POLLING_MODE, CONF_WEATHER_INTERVAL,
                     CONF_AQHI_INTERVAL, "weong_interval"):
            if key in new_data:
                new_options[key] = new_data.pop(key)
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2,
        )
        _LOGGER.info("EC Weather config entry migrated to version 2")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EC Weather from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    language = entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    city_code = entry.data[CONF_CITY_CODE]
    bbox = entry.data[CONF_BBOX]
    geomet_bbox = entry.data[CONF_GEOMET_BBOX]
    aqhi_location_id = entry.data.get(CONF_AQHI_LOCATION_ID)

    # Validate bbox formats at setup time
    if not validate_bbox(bbox):
        _LOGGER.warning("EC Weather: bbox value '%s' is not 4 comma-separated floats", bbox)
    if not validate_bbox(geomet_bbox):
        _LOGGER.warning("EC Weather: geomet_bbox value '%s' is not 4 comma-separated floats", geomet_bbox)

    # Read mutable settings from entry.options with fallback to defaults
    polling_mode = entry.options.get(CONF_POLLING_MODE, DEFAULT_POLLING_MODE)
    weather_interval = entry.options.get(CONF_WEATHER_INTERVAL, DEFAULT_WEATHER_INTERVAL)
    aqhi_interval = entry.options.get(CONF_AQHI_INTERVAL, DEFAULT_AQHI_INTERVAL)

    # Determine polling per coordinator based on mode
    weather_polls = polling_mode in (POLLING_MODE_EFFICIENT, POLLING_MODE_FULL)
    aqhi_polls = polling_mode in (POLLING_MODE_EFFICIENT, POLLING_MODE_FULL)

    weather_coordinator = ECWeatherCoordinator(
        hass, city_code, language=language,
        interval_minutes=weather_interval, polling=weather_polls,
    )
    alert_coordinator = ECAlertCoordinator(hass, bbox, language=language)
    aqhi_coordinator = ECAQHICoordinator(
        hass, aqhi_location_id,
        interval_minutes=aqhi_interval, polling=aqhi_polls,
    )
    weong_polls = polling_mode == POLLING_MODE_FULL
    # The extended-forecast checkbox gates the outlook days (legacy phase-C
    # select values are honored: "14" behaves as checked).
    # (7 official days, or 14 with
    # GEPS outlook rows). Stored as a string by the select; coerce to int.
    extended = bool(
        entry.options.get(
            CONF_EXTENDED_FORECAST,
            str(entry.options.get(CONF_FORECAST_DAYS, "")) == "14",
        )
    )
    forecast_days = EXTENDED_FORECAST_DAYS if extended else DEFAULT_FORECAST_DAYS
    weong_coordinator = ECWEonGCoordinator(
        hass, geomet_bbox, polling=weong_polls, forecast_days=forecast_days,
    )

    # Yesterday's precipitation — only when a station was discovered/opted in.
    precip_station_id = entry.data.get(CONF_PRECIP_STATION_ID)
    climate_coordinator = None
    if precip_station_id:
        climate_coordinator = ECClimateCoordinator(
            hass,
            precip_station_id,
            station_type=entry.data.get(CONF_PRECIP_STATION_TYPE, "combined"),
            station_name=entry.data.get(CONF_PRECIP_STATION_NAME),
            distance_km=entry.data.get(CONF_PRECIP_STATION_DISTANCE_KM),
        )

    # Fetch all three coordinators in parallel (~2s instead of ~6s sequential)
    weather_task = weather_coordinator.async_config_entry_first_refresh()
    alert_task = alert_coordinator.async_config_entry_first_refresh()

    async def _safe_aqhi_refresh():
        try:
            await aqhi_coordinator.async_config_entry_first_refresh()
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.debug("EC Weather: AQHI data not available, will retry")

    await asyncio.gather(weather_task, alert_task, _safe_aqhi_refresh())

    # Startup canary: verify the weather API response has expected keys
    if weather_coordinator.data:
        props_ok = all(k in weather_coordinator.data for k in ("current", "hourly", "daily"))
        if not props_ok:
            _LOGGER.warning("EC Weather: API response may have changed — some data keys missing")

    hass.data[DOMAIN][entry.entry_id] = ECWeatherData(
        weather=weather_coordinator,
        alerts=alert_coordinator,
        aqhi=aqhi_coordinator,
        weong=weong_coordinator,
        climate=climate_coordinator,
    )

    # Yesterday's precip is non-blocking — fetch in the background so a slow
    # or unpublished climate response never delays setup. It retries on its
    # own 30-min interval until yesterday publishes.
    if climate_coordinator is not None:
        entry.async_create_background_task(
            hass,
            climate_coordinator.async_refresh(),
            name="ec_weather_climate_first_refresh",
        )

    # Offer the yesterday-precipitation feature to users who haven't set it up.
    from .repairs import async_manage_precip_issue
    async_manage_precip_issue(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # WEonG makes ~100+ GeoMet requests — refresh in background.
    # Hourly/daily sections show loading state until WEonG data is ready.
    entry.async_create_background_task(
        hass, weong_coordinator.async_refresh(), "ec_weather_weong_refresh",
    )

    # Register the lazy timestep fetch service
    async def _handle_fetch_day_timesteps(call):
        date_str = call.data["date"]
        # Known limitation: iterates all entries and acts on the first match.
        # This is fine while config_flow.py enforces a single-instance guard.
        # When multi-instance support is added, this will need to accept an
        # entry_id parameter or dispatch to all instances.
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, ECWeatherData):
                await entry_data.weong.async_fetch_day_timesteps(date_str)
                return

    if not hass.services.has_service(DOMAIN, SERVICE_FETCH_DAY_TIMESTEPS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FETCH_DAY_TIMESTEPS,
            _handle_fetch_day_timesteps,
            schema=vol.Schema({vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$")}),
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
