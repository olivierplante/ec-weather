"""Typed runtime data and shared helpers for the EC Weather integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator.weather import ECWeatherCoordinator
    from .coordinator.alerts import ECAlertCoordinator
    from .coordinator.aqhi import ECAQHICoordinator
    from .coordinator.weong import ECWEonGCoordinator


@dataclass
class ECWeatherData:
    """Typed container for coordinator instances stored in hass.data."""

    weather: ECWeatherCoordinator
    alerts: ECAlertCoordinator
    aqhi: ECAQHICoordinator
    weong: ECWEonGCoordinator


def build_device_info(city_code: str, city_name: str) -> DeviceInfo:
    """Build a shared DeviceInfo for all entities from the same city."""
    return DeviceInfo(
        identifiers={(DOMAIN, city_code)},
        name=f"EC Weather \u2014 {city_name}",
        manufacturer="Environment and Climate Change Canada",
        model="Weather API",
        entry_type=DeviceEntryType.SERVICE,
    )
