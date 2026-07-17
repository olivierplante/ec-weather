"""Config flow for the EC Weather integration.

Three-step flow:
  1. City name search + language selection
  2. Disambiguation (if multiple matches — skipped for single match)
  3. Editable confirmation with auto-discovered AQHI/climate stations
"""

from __future__ import annotations

import asyncio
import logging
import math

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .api_client import (
    discover_aqhi_station,
    discover_precip_stations,
    parse_ec_city_features,
)
from .const import (
    CONF_AI_GROUPING,
    CONF_AI_GROUPING_INSTRUCTIONS,
    CONF_AI_TASK_ENTITY,
    CONF_AQHI_INTERVAL,
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_CITY_NAME,
    CONF_FORECAST_DAYS,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_MODEL_PRECIP_ESTIMATE,
    CONF_POLLING_MODE,
    CONF_PRECIP_DISCOVERED,
    CONF_PRECIP_STATION_DISTANCE_KM,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_NAME,
    CONF_PRECIP_STATION_TYPE,
    CONF_WEATHER_INTERVAL,
    DEFAULT_AI_GROUPING,
    DEFAULT_AI_GROUPING_INSTRUCTIONS,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MODEL_PRECIP_ESTIMATE,
    EXTENDED_FORECAST_DAYS,
    DEFAULT_LANGUAGE,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    CONF_EXTENDED_FORECAST,
    POLLING_MODES,
    REQUEST_TIMEOUT,
    SUPPORTED_LANGUAGES,
    resolve_ai_grouping_instructions,
)

_LOGGER = logging.getLogger(__name__)


PRECIP_OPT_OUT = "__none__"

# Collapsible form section that houses not-yet-stable, opt-in options. Its
# fields arrive nested under this key on submit and are flattened back into the
# top-level options so the stored format never changes.
CONF_BETA_SECTION = "beta"


def _precip_choice_label(station: dict, language: str) -> str:
    """Human label for a precip station: name, distance, and data type."""
    name = station.get("name") or station.get("station_id")
    distance = station.get("distance_km")
    is_split = station.get("type") == "split"
    if language == "fr":
        type_label = "pluie et neige séparées" if is_split else "précipitations combinées"
        dist_label = f"{distance} km" if distance is not None else "?"
        return f"{name} — {dist_label} — {type_label}"
    type_label = "rain & snow separately" if is_split else "combined precipitation"
    dist_label = f"{distance} km" if distance is not None else "?"
    return f"{name} — {dist_label} — {type_label}"


def build_precip_choices(discovery: dict, language: str) -> tuple[list, dict]:
    """Build selectable options + a value->station map from a discovery result.

    Presents the nearest reporting station and, when it is combined-only, the
    nearest split-capable station too (deduplicated when they are the same).
    Always appends an explicit opt-out as the last option.

    Returns ``(options, mapping)`` where options is a list of
    ``SelectOptionDict`` and mapping maps each option value to its station dict
    (or None for the opt-out).
    """
    options: list = []
    mapping: dict = {}

    seen: set[str] = set()
    for station in (discovery.get("nearest"), discovery.get("nearest_split")):
        if not station:
            continue
        sid = station["station_id"]
        if sid in seen:
            continue
        seen.add(sid)
        options.append(
            SelectOptionDict(value=sid, label=_precip_choice_label(station, language))
        )
        mapping[sid] = station

    opt_out_label = (
        "Don’t add yesterday’s precipitation"
        if language != "fr"
        else "Ne pas ajouter les précipitations d’hier"
    )
    options.append(SelectOptionDict(value=PRECIP_OPT_OUT, label=opt_out_label))
    mapping[PRECIP_OPT_OUT] = None

    return options, mapping


def precip_default_choice(options: list, current_station_id: str | None) -> str:
    """Return the value to pre-select in the precip chooser.

    The currently configured station when it is among the discovered options;
    otherwise the opt-out value.
    """
    if current_station_id and any(o["value"] == current_station_id for o in options):
        return current_station_id
    return PRECIP_OPT_OUT


def _compute_alert_bbox(lat: float, lon: float) -> str:
    """Compute a ~20km alert bounding box: lon-0.2,lat-0.2,lon+0.2,lat+0.2."""
    return f"{lon - 0.2:.1f},{lat - 0.2:.1f},{lon + 0.2:.1f},{lat + 0.2:.1f}"


def _compute_geomet_bbox(lat: float, lon: float) -> str:
    """Compute a 2° GeoMet WMS bounding box: lat-1.0,lon-1.0,lat+1.0,lon+1.0.

    EPSG:4326 axis order for WMS 1.3.0 is lat,lon.
    """
    return f"{lat - 1.0:.3f},{lon - 1.0:.3f},{lat + 1.0:.3f},{lon + 1.0:.3f}"



class ECWeatherOptionsFlow(config_entries.OptionsFlow):
    """Handle options for EC Weather."""

    def __init__(self) -> None:
        self._precip_choices: dict = {}

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Show editable settings."""
        mutable_keys = {
            CONF_POLLING_MODE, CONF_WEATHER_INTERVAL,
            CONF_AQHI_INTERVAL, CONF_EXTENDED_FORECAST,
            CONF_AI_GROUPING, CONF_AI_TASK_ENTITY,
            CONF_AI_GROUPING_INSTRUCTIONS,
            CONF_MODEL_PRECIP_ESTIMATE,
        }

        if user_input is not None:
            # The beta section's fields arrive nested under its section key.
            # Flatten them into the top level BEFORE the mutable/immutable
            # split so entry.options keeps the flat keys (ai_grouping /
            # ai_task_entity / ai_grouping_instructions) — no storage-format
            # change, no migration. A field cleared inside the section is
            # simply absent from the nested dict, so the cleared-entity pop
            # below still fires correctly.
            beta_section = user_input.pop(CONF_BETA_SECTION, {})
            user_input.update(beta_section)
            # Snapshot the pre-save state so the terminal step can tell a
            # checkbox-only change (in-place fast path) from one needing a
            # full reload.
            self._pre_flow_data = dict(self.config_entry.data)
            self._pre_flow_options = dict(self.config_entry.options)
            # Separate immutable data from mutable options
            new_data = dict(self.config_entry.data)
            new_options = dict(self.config_entry.options)
            for key, value in user_input.items():
                if key in mutable_keys:
                    new_options[key] = value
                else:
                    new_data[key] = value
            # The optional AI Task entity selector omits its key when cleared;
            # drop any stored value so clearing actually unsets it.
            if CONF_AI_TASK_ENTITY not in user_input:
                new_options.pop(CONF_AI_TASK_ENTITY, None)
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data, options=new_options,
            )
            # Always continue to the precipitation-station step so it can be
            # reviewed/changed every time. The reload happens there.
            return await self.async_step_precip()

        data = self.config_entry.data
        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CITY_CODE,
                        default=data.get(CONF_CITY_CODE, ""),
                    ): TextSelector(TextSelectorConfig(type="text")),
                    vol.Required(
                        CONF_LANGUAGE,
                        default=data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=k, label=v)
                                for k, v in SUPPORTED_LANGUAGES.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_BBOX,
                        default=data.get(CONF_BBOX, ""),
                    ): TextSelector(TextSelectorConfig(type="text")),
                    vol.Required(
                        CONF_GEOMET_BBOX,
                        default=data.get(CONF_GEOMET_BBOX, ""),
                    ): TextSelector(TextSelectorConfig(type="text")),
                    vol.Optional(
                        CONF_AQHI_LOCATION_ID,
                        default=data.get(CONF_AQHI_LOCATION_ID) or "",
                    ): TextSelector(TextSelectorConfig(type="text")),
                    vol.Optional(
                        CONF_POLLING_MODE,
                        default=options.get(
                            CONF_POLLING_MODE, DEFAULT_POLLING_MODE
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=k, label=v)
                                for k, v in POLLING_MODES.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_WEATHER_INTERVAL,
                        default=options.get(
                            CONF_WEATHER_INTERVAL, DEFAULT_WEATHER_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10, max=120, step=5,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_AQHI_INTERVAL,
                        default=options.get(
                            CONF_AQHI_INTERVAL, DEFAULT_AQHI_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=60, max=720, step=30,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_EXTENDED_FORECAST,
                        # Legacy phase-C select value ("14") pre-checks the box.
                        default=bool(
                            options.get(
                                CONF_EXTENDED_FORECAST,
                                str(options.get(CONF_FORECAST_DAYS, "")) == "14",
                            )
                        ),
                    ): bool,
                    # Not-yet-stable, opt-in options live in a collapsed
                    # "Beta" section. The fields keep their exact selectors,
                    # defaults, and suggested_value handling; only their
                    # placement changes. Submitted input arrives nested under
                    # this key and is flattened back to the top level above.
                    vol.Required(CONF_BETA_SECTION): section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    CONF_MODEL_PRECIP_ESTIMATE,
                                    default=bool(
                                        options.get(
                                            CONF_MODEL_PRECIP_ESTIMATE,
                                            DEFAULT_MODEL_PRECIP_ESTIMATE,
                                        )
                                    ),
                                ): bool,
                                vol.Optional(
                                    CONF_AI_GROUPING,
                                    default=bool(
                                        options.get(
                                            CONF_AI_GROUPING, DEFAULT_AI_GROUPING
                                        )
                                    ),
                                ): bool,
                                vol.Optional(
                                    CONF_AI_TASK_ENTITY,
                                    # Suggested-value (not a hard default): the
                                    # entity selector rejects "", so leaving it
                                    # blank must omit the key rather than
                                    # validate an empty string.
                                    description={
                                        "suggested_value": options.get(
                                            CONF_AI_TASK_ENTITY
                                        )
                                        or None,
                                    },
                                ): EntitySelector(
                                    EntitySelectorConfig(domain="ai_task")
                                ),
                                vol.Optional(
                                    CONF_AI_GROUPING_INSTRUCTIONS,
                                    # Show the upgraded default when the stored
                                    # value is blank or a superseded legacy
                                    # default; a customized value is shown
                                    # unchanged.
                                    default=resolve_ai_grouping_instructions(
                                        options.get(CONF_AI_GROUPING_INSTRUCTIONS)
                                    ),
                                ): TextSelector(
                                    TextSelectorConfig(type="text", multiline=True)
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            description_placeholders={
                "city_name": data.get(CONF_CITY_NAME, ""),
                "city_code": data.get(CONF_CITY_CODE, ""),
            },
        )

    async def async_step_precip(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Discover and choose yesterday's precipitation station (or opt out)."""
        data = self.config_entry.data
        language = data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

        if user_input is not None:
            station = self._precip_choices.get(user_input.get(CONF_PRECIP_STATION_ID))
            new_data = dict(self.config_entry.data)
            new_data[CONF_PRECIP_DISCOVERED] = True
            if station:
                new_data[CONF_PRECIP_STATION_ID] = station["station_id"]
                new_data[CONF_PRECIP_STATION_TYPE] = station["type"]
                new_data[CONF_PRECIP_STATION_NAME] = station["name"]
                new_data[CONF_PRECIP_STATION_DISTANCE_KM] = station["distance_km"]
            else:
                # Explicit opt-out — clear any previously chosen station.
                for key in (
                    CONF_PRECIP_STATION_ID, CONF_PRECIP_STATION_TYPE,
                    CONF_PRECIP_STATION_NAME, CONF_PRECIP_STATION_DISTANCE_KM,
                ):
                    new_data.pop(key, None)
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data,
            )
            # HA core assigns this terminal payload to entry.options — an
            # empty dict here silently WIPES every saved option after the
            # reload already ran with good values (lost-on-reboot bug).
            # Always hand back the full current options.
            options_now = dict(self.config_entry.options)

            # Fast path: when the extended-forecast checkbox is the only
            # change, skip the full reload and apply it in place — skeleton
            # outlook rows then appear instantly instead of after a reload
            # plus refetch cycle.
            pre_data = getattr(self, "_pre_flow_data", None)
            pre_options = getattr(self, "_pre_flow_options", None)
            # Compare EFFECTIVE values (missing key == its default), or an
            # empty options store would make every default-filled save look
            # like a change and defeat the fast path.
            option_defaults = {
                CONF_POLLING_MODE: DEFAULT_POLLING_MODE,
                CONF_WEATHER_INTERVAL: DEFAULT_WEATHER_INTERVAL,
                CONF_AQHI_INTERVAL: DEFAULT_AQHI_INTERVAL,
                # AI options must gate the reload too — changing any of them
                # would otherwise take the checkbox-only fast path and never
                # reload the alert coordinator with the new settings.
                CONF_AI_GROUPING: DEFAULT_AI_GROUPING,
                CONF_AI_TASK_ENTITY: None,
                CONF_AI_GROUPING_INSTRUCTIONS: DEFAULT_AI_GROUPING_INSTRUCTIONS,
                # The estimated-precip toggle must gate the reload too — a
                # change would otherwise take the checkbox-only fast path and
                # never rebuild the daily sensor with the new setting.
                CONF_MODEL_PRECIP_ESTIMATE: DEFAULT_MODEL_PRECIP_ESTIMATE,
            }
            others_unchanged = pre_options is not None and all(
                options_now.get(key, default)
                == pre_options.get(key, default)
                for key, default in option_defaults.items()
            )
            def _normalized(payload: dict) -> dict:
                # Empty strings from untouched text fields round-trip stored
                # None values; treat them as equal so a no-op save stays a
                # no-op.
                return {
                    key: (None if value == "" else value)
                    for key, value in payload.items()
                    if key != CONF_PRECIP_DISCOVERED
                }

            data_unchanged = pre_data is not None and _normalized(
                dict(self.config_entry.data)
            ) == _normalized(pre_data)
            checkbox_only = others_unchanged and data_unchanged
            entry_data = self.hass.data.get(DOMAIN, {}).get(
                self.config_entry.entry_id,
            )
            if checkbox_only and entry_data is not None:
                extended = bool(options_now.get(CONF_EXTENDED_FORECAST, False))
                entry_data.weong.apply_forecast_days(
                    EXTENDED_FORECAST_DAYS if extended else DEFAULT_FORECAST_DAYS,
                )
            else:
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id,
                )
            return self.async_create_entry(title="", data=options_now)

        session = async_get_clientsession(self.hass)
        discovery = await discover_precip_stations(
            session=session,
            lat=data.get(CONF_LAT) or 0.0,
            lon=data.get(CONF_LON) or 0.0,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )
        options, self._precip_choices = build_precip_choices(discovery, language)

        # Pre-select the currently configured station so the form shows the
        # existing choice; fall back to opt-out when none is set or it isn't
        # in the discovered options.
        default = precip_default_choice(options, data.get(CONF_PRECIP_STATION_ID))

        return self.async_show_form(
            step_id="precip",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRECIP_STATION_ID, default=default
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={"city_name": data.get(CONF_CITY_NAME, "")},
        )


class ECWeatherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EC Weather."""

    VERSION = 2

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ECWeatherOptionsFlow:
        """Get the options flow handler."""
        return ECWeatherOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._cities: list[dict] = []
        self._cities_language: str = DEFAULT_LANGUAGE
        self._selected_city: dict = {}
        self._discovered_aqhi: str | None = None
        self._auto_detected: bool = False
        self._pending_entry_data: dict | None = None
        self._precip_choices: dict = {}

    # ------------------------------------------------------------------
    # Step 1: City name search + language (with auto-detection)
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step — city name search with auto-detection."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}

        # Auto-detect on first load (user_input is None)
        if user_input is None:
            auto_city = await self._auto_detect_city()
            if auto_city:
                default_query = auto_city.get("name", "")
            else:
                default_query = ""
        else:
            default_query = ""

        if user_input is not None:
            city_query = user_input.get("city_query", "").strip()
            language = user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

            if not city_query:
                errors["city_query"] = "no_city_name"
            else:
                # Fetch all EC cities and filter
                try:
                    matches = await self._search_cities(city_query, language)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    errors["city_query"] = "api_error"
                    matches = []

                if not errors:
                    if not matches:
                        errors["city_query"] = "no_city_found"
                    elif len(matches) == 1:
                        # Single match — skip disambiguation
                        self._selected_city = matches[0]
                        self._selected_city["language"] = language
                        return await self._run_discovery()
                    else:
                        # Multiple matches — go to disambiguation
                        self._cities = matches
                        self._cities_language = language
                        return await self.async_step_select_city()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("city_query", default=default_query): TextSelector(
                        TextSelectorConfig(type="text")
                    ),
                    vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=k, label=v)
                                for k, v in SUPPORTED_LANGUAGES.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def _auto_detect_city(self) -> dict | None:
        """Find the nearest EC city using HA's home coordinates."""
        lat = self.hass.config.latitude
        lon = self.hass.config.longitude
        if not lat or not lon:
            return None

        # Query EC cities within a ~1 deg bbox around home location
        bbox = f"{lon - 1.0:.1f},{lat - 1.0:.1f},{lon + 1.0:.1f},{lat + 1.0:.1f}"
        url = (
            f"{EC_API_BASE}/collections/citypageweather-realtime/items"
            f"?f=json&lang=en&skipGeometry=true&bbox={bbox}&limit=50"
        )
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("Auto-detect city failed: %s", err)
            return None

        features = data.get("features") or []
        if not features:
            return None

        # Parse cities using shared helper and find the nearest one
        cities = parse_ec_city_features(features, language="en")

        # Filter to cities with coordinates and compute distance
        with_coords = []
        for city in cities:
            if city["lat"] is not None and city["lon"] is not None:
                dlat = city["lat"] - lat
                dlon = (city["lon"] - lon) * math.cos(math.radians(lat))
                dist = dlat ** 2 + dlon ** 2
                with_coords.append({**city, "dist": dist})

        if not with_coords:
            return None

        # Return the nearest city
        with_coords.sort(key=lambda c: c["dist"])
        nearest = with_coords[0]
        _LOGGER.debug(
            "Auto-detected nearest EC city: %s (%s) at %.4f, %.4f",
            nearest["name"], nearest["id"], nearest["lat"], nearest["lon"],
        )
        return nearest

    async def _search_cities(self, query: str, language: str) -> list[dict]:
        """Search EC cities using server-side name filter.

        Uses the name.{lang} queryable field for server-side substring matching.
        This returns ~35KB per match instead of downloading all 844 cities (30MB).
        Coordinates are parsed from the URL field since skipGeometry=true.
        """
        lang_key = "fr" if language == "fr" else "en"
        url = (
            f"{EC_API_BASE}/collections/citypageweather-realtime/items"
            f"?f=json&lang={language}&skipGeometry=true"
            f"&name.{lang_key}={query}"
        )
        session = async_get_clientsession(self.hass)

        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()

        features = data.get("features") or []
        matches = parse_ec_city_features(features, language=language)
        matches.sort(key=lambda c: c["name"])
        return matches

    # ------------------------------------------------------------------
    # Step 2: Disambiguation (multiple city matches)
    # ------------------------------------------------------------------

    async def async_step_select_city(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle city disambiguation when multiple matches are found."""
        if user_input is not None:
            selected_id = user_input.get("city_id")
            for city in self._cities:
                if city["id"] == selected_id:
                    self._selected_city = city
                    self._selected_city["language"] = self._cities_language
                    break
            return await self._run_discovery()

        options = [
            SelectOptionDict(
                value=c["id"],
                label=f"{c['name']} ({c['province']})",
            )
            for c in self._cities
        ]

        return self.async_show_form(
            step_id="select_city",
            data_schema=vol.Schema(
                {
                    vol.Required("city_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    # ------------------------------------------------------------------
    # Auto-discovery
    # ------------------------------------------------------------------

    async def _run_discovery(self) -> FlowResult:
        """Auto-discover AQHI and climate stations, then show confirmation."""
        lat = self._selected_city.get("lat")
        lon = self._selected_city.get("lon")

        if lat is not None and lon is not None:
            self._discovered_aqhi = await self._discover_aqhi_station(lat, lon)
        else:
            self._discovered_aqhi = None

        return await self.async_step_confirm()

    async def _discover_aqhi_station(self, lat: float, lon: float) -> str | None:
        """Find the nearest AQHI forecast station within +/-1.5 deg of the city."""
        session = async_get_clientsession(self.hass)
        return await discover_aqhi_station(
            session=session,
            lat=lat,
            lon=lon,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Step 3: Editable confirmation
    # ------------------------------------------------------------------

    async def async_step_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Show auto-discovered values and let the user edit them."""
        city = self._selected_city
        lat = city.get("lat") or 0.0
        lon = city.get("lon") or 0.0
        language = city.get("language", DEFAULT_LANGUAGE)

        if user_input is not None:
            # User confirmed (possibly with edits). Stash the data and move on
            # to the precipitation-station selection step.
            final_lat = user_input[CONF_LAT]
            final_lon = user_input[CONF_LON]

            self._pending_entry_data = {
                CONF_CITY_CODE: city["id"],
                CONF_CITY_NAME: city.get("name", city.get("id", "")),
                CONF_LANGUAGE: language,
                CONF_LAT: final_lat,
                CONF_LON: final_lon,
                CONF_BBOX: user_input[CONF_BBOX],
                CONF_GEOMET_BBOX: user_input[CONF_GEOMET_BBOX],
                CONF_AQHI_LOCATION_ID: user_input.get(CONF_AQHI_LOCATION_ID) or None,
            }
            return await self.async_step_precip()

        # Pre-fill with auto-discovered values
        default_bbox = _compute_alert_bbox(lat, lon)
        default_geomet_bbox = _compute_geomet_bbox(lat, lon)

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LAT, default=round(lat, 4)): vol.Coerce(float),
                    vol.Required(CONF_LON, default=round(lon, 4)): vol.Coerce(float),
                    vol.Required(CONF_BBOX, default=default_bbox): TextSelector(
                        TextSelectorConfig(type="text")
                    ),
                    vol.Required(CONF_GEOMET_BBOX, default=default_geomet_bbox): TextSelector(
                        TextSelectorConfig(type="text")
                    ),
                    vol.Optional(
                        CONF_AQHI_LOCATION_ID,
                        default=self._discovered_aqhi or "",
                    ): TextSelector(TextSelectorConfig(type="text")),
                }
            ),
            description_placeholders={
                "city_name": city.get("name", ""),
                "province": city.get("province", ""),
                "city_code": city.get("id", ""),
            },
        )

    # ------------------------------------------------------------------
    # Step 4: Yesterday's precipitation station selection (issue #9)
    # ------------------------------------------------------------------

    async def async_step_precip(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Offer the nearest reporting / split-capable station, or opt out."""
        data = self._pending_entry_data or {}
        language = data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

        if user_input is not None:
            station = self._precip_choices.get(user_input.get(CONF_PRECIP_STATION_ID))
            final_data = dict(data)
            final_data[CONF_PRECIP_DISCOVERED] = True
            if station:
                final_data[CONF_PRECIP_STATION_ID] = station["station_id"]
                final_data[CONF_PRECIP_STATION_TYPE] = station["type"]
                final_data[CONF_PRECIP_STATION_NAME] = station["name"]
                final_data[CONF_PRECIP_STATION_DISTANCE_KM] = station["distance_km"]
            return self.async_create_entry(
                title=data.get(CONF_CITY_NAME) or data.get(CONF_CITY_CODE, "Unknown"),
                data=final_data,
            )

        # Run discovery using the confirmed coordinates.
        session = async_get_clientsession(self.hass)
        discovery = await discover_precip_stations(
            session=session,
            lat=data.get(CONF_LAT) or 0.0,
            lon=data.get(CONF_LON) or 0.0,
            api_base=EC_API_BASE,
            timeout=REQUEST_TIMEOUT,
        )

        options, self._precip_choices = build_precip_choices(discovery, language)

        # When nothing reports nearby, only the opt-out exists — skip the step
        # entirely rather than show a dead-end form.
        if len(options) == 1:
            final_data = dict(data)
            final_data[CONF_PRECIP_DISCOVERED] = True
            return self.async_create_entry(
                title=data.get(CONF_CITY_NAME) or data.get(CONF_CITY_CODE, "Unknown"),
                data=final_data,
            )

        return self.async_show_form(
            step_id="precip",
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
            description_placeholders={"city_name": data.get(CONF_CITY_NAME, "")},
        )
