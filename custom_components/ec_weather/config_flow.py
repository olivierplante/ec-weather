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
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
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

from .api_client import discover_aqhi_station, parse_ec_city_features
from .const import (
    CONF_AQHI_INTERVAL,
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_CITY_NAME,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_POLLING_MODE,
    CONF_WEATHER_INTERVAL,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    POLLING_MODES,
    REQUEST_TIMEOUT,
    SUPPORTED_LANGUAGES,
)

_LOGGER = logging.getLogger(__name__)


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

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Show editable settings."""
        mutable_keys = {
            CONF_POLLING_MODE, CONF_WEATHER_INTERVAL,
            CONF_AQHI_INTERVAL,
        }

        if user_input is not None:
            # Separate immutable data from mutable options
            new_data = dict(self.config_entry.data)
            new_options = dict(self.config_entry.options)
            for key, value in user_input.items():
                if key in mutable_keys:
                    new_options[key] = value
                else:
                    new_data[key] = value
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data, options=new_options,
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

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
                }
            ),
            description_placeholders={
                "city_name": data.get(CONF_CITY_NAME, ""),
                "city_code": data.get(CONF_CITY_CODE, ""),
            },
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
            # User confirmed (possibly with edits)
            final_lat = user_input[CONF_LAT]
            final_lon = user_input[CONF_LON]

            return self.async_create_entry(
                title=city.get("name", city.get("id", "Unknown")),
                data={
                    CONF_CITY_CODE: city["id"],
                    CONF_CITY_NAME: city.get("name", city.get("id", "")),
                    CONF_LANGUAGE: language,
                    CONF_LAT: final_lat,
                    CONF_LON: final_lon,
                    CONF_BBOX: user_input[CONF_BBOX],
                    CONF_GEOMET_BBOX: user_input[CONF_GEOMET_BBOX],
                    CONF_AQHI_LOCATION_ID: user_input.get(CONF_AQHI_LOCATION_ID) or None,
                },
            )

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
