"""Repairs platform — prompt existing users about yesterday's precipitation.

Existing installs predate the yesterday-precipitation feature and won't know
it exists. On setup we raise a fixable HA repair issue (WARNING severity)
whose flow runs station discovery and lets the user opt in — making it a
genuinely actionable repair rather than a passive advert. The issue is only
raised when the feature is unconfigured AND discovery hasn't run yet, and it
is deleted once the user configures (or explicitly opts out of) the feature.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api_client import discover_precip_stations
from .config_flow import PRECIP_OPT_OUT, build_precip_choices
from .const import (
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_PRECIP_DISCOVERED,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
    DEFAULT_LANGUAGE,
    DOMAIN,
    EC_API_BASE,
    REQUEST_TIMEOUT,
)

PRECIP_ISSUE_ID = "yesterday_precip_available"


def should_offer_precip_repair(entry_data: dict) -> bool:
    """Return True if the yesterday-precip repair should be offered.

    Pure predicate: offer only when no station is configured and discovery
    hasn't been run for this entry yet (avoids re-probing/re-nagging).
    """
    if entry_data.get(CONF_PRECIP_STATION_ID):
        return False
    if entry_data.get(CONF_PRECIP_DISCOVERED):
        return False
    return True


def async_manage_precip_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or remove the precip repair issue based on entry state."""
    if should_offer_precip_repair(dict(entry.data)):
        ir.async_create_issue(
            hass,
            DOMAIN,
            PRECIP_ISSUE_ID,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=PRECIP_ISSUE_ID,
            data={"entry_id": entry.entry_id},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, PRECIP_ISSUE_ID)


class PrecipRepairFlow(RepairsFlow):
    """Fix flow that discovers and configures a precipitation station."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._choices: dict = {}

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_choose()

    async def async_step_choose(
        self, user_input: dict | None = None
    ) -> data_entry_flow.FlowResult:
        data = self._entry.data
        language = data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

        if user_input is not None:
            station = self._choices.get(user_input.get(CONF_PRECIP_STATION_ID))
            new_data = dict(self._entry.data)
            new_data[CONF_PRECIP_DISCOVERED] = True
            if station:
                new_data[CONF_PRECIP_STATION_ID] = station["station_id"]
                new_data[CONF_PRECIP_STATION_TYPE] = station["type"]
                new_data[CONF_PRECIP_STATION_NAME] = station["name"]
                new_data[CONF_PRECIP_STATION_DISTANCE_KM] = station["distance_km"]
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            # Resolving the flow removes the issue automatically.
            return self.async_create_entry(title="", data={})

        session = async_get_clientsession(self.hass)
        discovery = await discover_precip_stations(
            session=session,
            lat=data.get(CONF_LAT) or 0.0,
            lon=data.get(CONF_LON) or 0.0,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )
        options, self._choices = build_precip_choices(discovery, language)

        return self.async_show_form(
            step_id="choose",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRECIP_STATION_ID, default=PRECIP_OPT_OUT
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict | None,
) -> RepairsFlow:
    """Create the repair flow for a given issue."""
    entry_id = (data or {}).get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    return PrecipRepairFlow(entry)
