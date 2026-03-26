"""Binary sensor platform for the EC Weather integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_CODE, CONF_CITY_NAME, DOMAIN
from .coordinator import ECAlertCoordinator
from .models import ECWeatherData, build_device_info


class ECAlertActiveSensor(CoordinatorEntity[ECAlertCoordinator], BinarySensorEntity):
    """Binary sensor — on when at least one active alert exists.

    Entity ID: binary_sensor.ec_alert_active
    Matches the entity ID produced by the native EC integration so that
    existing dashboard cards and automations continue to work unchanged.
    """

    _attr_has_entity_name = True
    _attr_name = "Alert Active"

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str, city_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alert_active_{city_code}"
        self._attr_device_info = build_device_info(city_code, city_name)

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        return (self.coordinator.data.get("alert_count") or 0) > 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EC Weather binary sensor entities from a config entry."""
    data: ECWeatherData = hass.data[DOMAIN][entry.entry_id]
    city_code = entry.data[CONF_CITY_CODE]
    city_name = entry.data.get(CONF_CITY_NAME, city_code)
    async_add_entities([ECAlertActiveSensor(data.alerts, city_code, city_name)])
