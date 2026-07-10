"""Typed runtime data and shared helpers for the EC Weather integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .coordinator.weather import ECWeatherCoordinator
    from .coordinator.alerts import ECAlertCoordinator
    from .coordinator.aqhi import ECAQHICoordinator
    from .coordinator.weong import ECWEonGCoordinator
    from .coordinator.climate import ECClimateCoordinator


@dataclass
class ECWeatherData:
    """Typed container for coordinator instances stored in hass.data."""

    weather: ECWeatherCoordinator
    alerts: ECAlertCoordinator
    aqhi: ECAQHICoordinator
    weong: ECWEonGCoordinator
    # Yesterday's precipitation — None when no station is configured (issue #9).
    climate: ECClimateCoordinator | None = None


def build_device_info(city_code: str, city_name: str) -> DeviceInfo:
    """Build a shared DeviceInfo for all entities from the same city."""
    return DeviceInfo(
        identifiers={(DOMAIN, city_code)},
        name=f"EC Weather \u2014 {city_name}",
        manufacturer="Environment and Climate Change Canada",
        model="Weather API",
        entry_type=DeviceEntryType.SERVICE,
    )


def migrate_short_entity_ids(
    hass: HomeAssistant, domain: str, unique_id_to_entity_id: dict[str, str]
) -> None:
    """Rename registry entities stuck on device-prefixed ids to the short form.

    entity_id is only honoured at first registration, so entities created by
    an earlier build keep their old id. Rename them to the id the card reads.
    Skips when the target id is already taken (avoids collisions, e.g. a
    second config entry).

    Only ids matching the auto-generated device-prefixed form
    (<domain>.ec_weather_...) are renamed — an id that matches neither the
    short form nor that prefix was chosen by the user, and user renames
    must be preserved.
    """
    from homeassistant.helpers import entity_registry as er

    generated_prefix = f"{domain}.ec_weather_"
    registry = er.async_get(hass)
    for unique_id, desired in unique_id_to_entity_id.items():
        current = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if not current or current == desired:
            continue
        if not current.startswith(generated_prefix):
            continue
        # Only rename if the target id is free, to avoid collisions.
        if registry.async_get(desired) is None:
            registry.async_update_entity(current, new_entity_id=desired)
            _LOGGER.debug("Migrated %s -> %s", current, desired)
