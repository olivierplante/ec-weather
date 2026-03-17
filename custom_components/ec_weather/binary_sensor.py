"""Binary sensor platform for the EC Weather integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_CODE, COORDINATOR_ALERTS, DOMAIN
from .coordinator import ECAlertCoordinator


class ECAlertActiveSensor(CoordinatorEntity[ECAlertCoordinator], BinarySensorEntity):
    """Binary sensor — on when at least one active alert exists.

    Entity ID: binary_sensor.ec_alert_active
    Matches the entity ID produced by the native EC integration so that
    existing dashboard cards and automations continue to work unchanged.
    """

    _attr_name = "EC Alert Active"

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alert_active_{city_code}"

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
    coordinator: ECAlertCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_ALERTS]
    city_code = entry.data[CONF_CITY_CODE]
    async_add_entities([ECAlertActiveSensor(coordinator, city_code)])
