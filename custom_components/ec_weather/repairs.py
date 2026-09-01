"""Repairs platform.

Two repairs live here, both following the same shape (pure predicate +
async_manage_*_issue + a RepairsFlow subclass), dispatched from a single
async_create_fix_flow keyed on issue_id:

- Yesterday's precipitation: existing installs predate the feature and won't
  know it exists. On setup we raise a fixable HA repair issue (WARNING
  severity) whose flow runs station discovery and lets the user opt in. Only
  raised when the feature is unconfigured AND discovery hasn't run yet;
  deleted once the user configures (or explicitly opts out of) the feature.

- Station data gap: existing installs that onboarded before the
  station_choice step never learned their citypage structurally omits some
  current-conditions data. The flow names the gaps and offers switching to
  the nearest fully-reporting citypage, or keeping the station (persistent
  dismissal, re-armed if the user later switches city).
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
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api_client import (
    AqhiDiscoveryError,
    discover_aqhi_station,
    discover_precip_stations,
    find_nearest_complete_city,
)
from .config_flow import (
    PRECIP_OPT_OUT,
    STATION_CHOICE_KEEP,
    STATION_CHOICE_SWITCH,
    _compute_alert_bbox,
    _compute_geomet_bbox,
    _missing_points_label,
    _station_choice_name,
    build_precip_choices,
)
from .const import (
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_CITY_NAME,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_PRECIP_DISCOVERED,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
    CONF_STATION_GAP_DISMISSED_FOR,
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


STATION_GAP_ISSUE_ID = "station_data_gap"


def should_offer_station_gap_repair(entry_data: dict, station_missing: list) -> bool:
    """Return True if the station-data-gap repair should be offered.

    Pure predicate: offer when the citypage has any missing data points AND
    the user hasn't dismissed the repair for THIS city_code. A prior
    dismissal for a different city_code (the user has since switched city)
    does not suppress the repair — it re-arms.
    """
    if not station_missing:
        return False
    return entry_data.get(CONF_STATION_GAP_DISMISSED_FOR) != entry_data.get(CONF_CITY_CODE)


def async_manage_station_gap_issue(
    hass: HomeAssistant, entry: ConfigEntry, station_missing: list
) -> None:
    """Create or remove the station-data-gap repair issue based on entry state."""
    data = dict(entry.data)
    if should_offer_station_gap_repair(data, station_missing):
        language = data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        ir.async_create_issue(
            hass,
            DOMAIN,
            STATION_GAP_ISSUE_ID,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=STATION_GAP_ISSUE_ID,
            data={"entry_id": entry.entry_id},
            translation_placeholders={
                "city_name": data.get(CONF_CITY_NAME, ""),
                "missing_points": _missing_points_label(station_missing, language),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, STATION_GAP_ISSUE_ID)


class StationGapRepairFlow(RepairsFlow):
    """Fix flow for a citypage that structurally omits current-conditions data.

    Mirrors the onboarding station_choice step in config_flow.py: lets the
    user keep the current citypage (now knowing what's missing — the
    dismissal is remembered per city_code, so switching city later re-arms
    the repair) or switch to the nearest citypage that reports everything.
    """

    def __init__(self, entry: ConfigEntry, station_missing: list) -> None:
        self._entry = entry
        self._station_missing = station_missing
        self._alternative: dict | None = None

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_choose()

    async def async_step_choose(
        self, user_input: dict | None = None
    ) -> data_entry_flow.FlowResult:
        data = self._entry.data
        language = data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        city_name = data.get(CONF_CITY_NAME, "")

        if user_input is not None:
            if user_input.get("choice") == STATION_CHOICE_SWITCH and self._alternative:
                await self._switch_to_alternative(language)
            else:
                new_data = dict(self._entry.data)
                new_data[CONF_STATION_GAP_DISMISSED_FOR] = new_data.get(CONF_CITY_CODE)
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                # Dismissal only affects repair-offer gating — no reload needed.
            return self.async_create_entry(title="", data={})

        session = async_get_clientsession(self.hass)
        self._alternative = await find_nearest_complete_city(
            session=session,
            lat=data.get(CONF_LAT) or 0.0,
            lon=data.get(CONF_LON) or 0.0,
            exclude_id=data.get(CONF_CITY_CODE, ""),
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )

        keep_label = (
            f"Garder {city_name}" if language == "fr" else f"Keep {city_name}"
        )
        options = [SelectOptionDict(value=STATION_CHOICE_KEEP, label=keep_label)]

        # Mirrors config_flow.py's onboarding station_choice step: a single
        # pre-composed alternative_sentence placeholder, built in Python
        # since description_placeholders text is only static translation —
        # not the same mechanism as the fix_flow selector options above.
        if self._alternative:
            alt = self._alternative
            alt_name = _station_choice_name(alt["name"], language, alt["id"])
            distance_label = f"{alt['distance_km']} km"
            switch_label = (
                f"Passer à {alt_name} — {distance_label}"
                if language == "fr"
                else f"Switch to {alt_name} — {distance_label}"
            )
            options.append(
                SelectOptionDict(value=STATION_CHOICE_SWITCH, label=switch_label)
            )
            alternative_sentence = (
                f"La station la plus proche qui rapporte tout est "
                f"{alt_name}, à environ {distance_label}."
                if language == "fr"
                else f"The nearest citypage that reports everything is "
                f"{alt_name}, about {distance_label} away."
            )
        else:
            alternative_sentence = (
                "Aucune station à proximité rapportant tout n'a été trouvée."
                if language == "fr"
                else "No nearby citypage reporting everything was found."
            )

        return self.async_show_form(
            step_id="choose",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "choice", default=STATION_CHOICE_KEEP
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "city_name": city_name,
                "missing_points": _missing_points_label(self._station_missing, language),
                "alternative_sentence": alternative_sentence,
            },
        )

    async def _switch_to_alternative(self, language: str) -> None:
        """Move the entry to the alternative citypage and reload.

        Precip-station settings are deliberately left untouched here — they
        stay pointed at whatever climate station was configured (or not) for
        the old location. The user can rerun precip discovery for the new
        location via the options flow.
        """
        alt = self._alternative
        new_lat = alt["lat"]
        new_lon = alt["lon"]

        new_data = dict(self._entry.data)
        new_data[CONF_CITY_CODE] = alt["id"]
        new_data[CONF_CITY_NAME] = _station_choice_name(alt["name"], language, alt["id"])
        new_data[CONF_LAT] = new_lat
        new_data[CONF_LON] = new_lon
        new_data[CONF_BBOX] = _compute_alert_bbox(new_lat, new_lon)
        new_data[CONF_GEOMET_BBOX] = _compute_geomet_bbox(new_lat, new_lon)

        session = async_get_clientsession(self.hass)
        try:
            new_aqhi_id = await discover_aqhi_station(
                session=session,
                lat=new_lat,
                lon=new_lon,
                api_base=EC_API_BASE,
                timeout=REQUEST_TIMEOUT,
            )
        except AqhiDiscoveryError:
            # A failed request behaves exactly like a "no station found"
            # answer here — keep the old AQHI id, same as today.
            new_aqhi_id = None
        if new_aqhi_id is not None:
            new_data[CONF_AQHI_LOCATION_ID] = new_aqhi_id
        # else: keep the old AQHI id already carried over via dict(self._entry.data)

        new_data.pop(CONF_STATION_GAP_DISMISSED_FOR, None)

        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        await self.hass.config_entries.async_reload(self._entry.entry_id)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict | None,
) -> RepairsFlow:
    """Create the repair flow for a given issue."""
    entry_id = (data or {}).get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if issue_id == STATION_GAP_ISSUE_ID:
        station_missing: list = []
        bundle = hass.data.get(DOMAIN, {}).get(entry_id) if entry_id else None
        weather_coordinator = getattr(bundle, "weather", None)
        if weather_coordinator is not None and weather_coordinator.data:
            station_missing = weather_coordinator.data.get("station_missing") or []
        return StationGapRepairFlow(entry, station_missing)
    return PrecipRepairFlow(entry)
