"""Websocket command that resolves the card's entity roles server-side.

The Lovelace card reads its entities by a stable machine-readable ROLE rather
than a hardcoded entity_id. This command owns that contract: it resolves each
role to a live entity_id from the entity registry by unique_id — the true
identity the integration owns — so user renames of the display entity_id never
break the card (issue #12).

Registered once in async_setup (not per entry); it answers for every loaded
config entry. See the dev docs "Extending the WebSocket API".
"""

from __future__ import annotations

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

import voluptuous as vol

from .const import CONF_CITY_CODE, CONF_CITY_NAME, DOMAIN

# role -> (domain, unique_id slug). Roles are the contract the card consumes;
# treat them as immutable once released.
CARD_ROLES = {
    "temperature": ("sensor", "ec_temperature"),
    "feels_like": ("sensor", "ec_feels_like"),
    "humidity": ("sensor", "ec_humidity"),
    "wind_speed": ("sensor", "ec_wind_speed"),
    "wind_gust": ("sensor", "ec_wind_gust"),
    "wind_direction": ("sensor", "ec_wind_direction"),
    "condition": ("sensor", "ec_condition"),
    "icon_code": ("sensor", "ec_icon_code"),
    "sunrise": ("sensor", "ec_sunrise"),
    "sunset": ("sensor", "ec_sunset"),
    "hourly_forecast": ("sensor", "ec_hourly_forecast"),
    "daily_forecast": ("sensor", "ec_daily_forecast"),
    "air_quality": ("sensor", "ec_aqhi"),
    "alerts": ("sensor", "ec_alerts"),
    "alert_active": ("binary_sensor", "ec_alert_active"),
    "precip_probability_today": ("sensor", "ec_precip_probability_today"),
    "yesterday_rain": ("sensor", "ec_yesterday_rain"),
    "yesterday_snow": ("sensor", "ec_yesterday_snow"),
    "yesterday_precipitation": ("sensor", "ec_yesterday_precipitation"),
}


@websocket_api.websocket_command({vol.Required("type"): "ec_weather/entities"})
@callback
def websocket_get_entities(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Resolve card roles to live entity_ids for every loaded config entry."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    entries_payload: list[dict] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        # An entry mid-setup or errored has no registry entities to resolve.
        if entry.state is not ConfigEntryState.LOADED:
            continue

        city_code = entry.data.get(CONF_CITY_CODE)
        city_name = entry.data.get(CONF_CITY_NAME)

        device = device_registry.async_get_device(identifiers={(DOMAIN, city_code)})
        device_id = device.id if device else None

        roles: dict[str, str] = {}
        for role, (domain, slug) in CARD_ROLES.items():
            entity_id = entity_registry.async_get_entity_id(
                domain, DOMAIN, f"{slug}_{city_code}"
            )
            # Missing/never-created entities (e.g. precip sensors when no
            # station is configured) are omitted, not an error.
            if entity_id is not None:
                roles[role] = entity_id

        entries_payload.append(
            {
                "entry_id": entry.entry_id,
                "device_id": device_id,
                "city_name": city_name,
                "roles": roles,
            }
        )

    connection.send_result(msg["id"], {"entries": entries_payload})


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the ec_weather websocket commands (called once from async_setup)."""
    websocket_api.async_register_command(hass, websocket_get_entities)
