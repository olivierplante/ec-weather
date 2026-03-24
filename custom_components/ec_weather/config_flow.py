"""Config flow for the EC Weather integration.

Three-step flow:
  1. City name search + language selection
  2. Disambiguation (if multiple matches — skipped for single match)
  3. Editable confirmation with auto-discovered AQHI/climate stations
"""

from __future__ import annotations

import asyncio
import logging
import re

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
    CONF_WEONG_INTERVAL,
    DEFAULT_AQHI_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_POLLING_MODE,
    DEFAULT_WEATHER_INTERVAL,
    DEFAULT_WEONG_INTERVAL,
    DOMAIN,
    EC_API_BASE,
    POLLING_MODES,
    REQUEST_TIMEOUT,
    SUPPORTED_LANGUAGES,
)

_LOGGER = logging.getLogger(__name__)

# Pattern to extract lat,lon from EC weather URL: coords=45.82,-73.96
_COORDS_RE = re.compile(r"coords=([-\d.]+),([-\d.]+)")


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
        if user_input is not None:
            # Update config entry data with new values
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            # Reload the integration to apply changes
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        data = self.config_entry.data

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
                        default=data.get(
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
                        default=data.get(
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
                        default=data.get(
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
                        CONF_WEONG_INTERVAL,
                        default=data.get(
                            CONF_WEONG_INTERVAL, DEFAULT_WEONG_INTERVAL
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

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ECWeatherOptionsFlow:
        """Get the options flow handler."""
        return ECWeatherOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._cities: list[dict] = []
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

        # Query EC cities within a ~1° bbox around home location
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

        # Parse cities and find the nearest one
        cities = []
        for feature in features:
            city_id = feature.get("id", "")
            props = feature.get("properties") or {}
            name = props.get("name")
            if isinstance(name, dict):
                name = name.get("en") or ""
            if not name:
                name = city_id

            province = city_id.split("-")[0].upper() if "-" in city_id else ""

            city_lat = None
            city_lon = None
            url_str = (props.get("url") or {}).get("en", "")
            match = _COORDS_RE.search(url_str)
            if match:
                city_lat = float(match.group(1))
                city_lon = float(match.group(2))

            if city_lat is not None and city_lon is not None:
                dist = (city_lat - lat) ** 2 + (city_lon - lon) ** 2
                cities.append({
                    "id": city_id,
                    "name": name,
                    "province": province,
                    "lat": city_lat,
                    "lon": city_lon,
                    "dist": dist,
                })

        if not cities:
            return None

        # Return the nearest city
        cities.sort(key=lambda c: c["dist"])
        nearest = cities[0]
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
        matches = []

        for feature in features:
            city_id = feature.get("id", "")
            props = feature.get("properties") or {}

            name = props.get("name")
            if isinstance(name, dict):
                name = name.get(language) or name.get("en") or ""
            if not name:
                name = city_id

            # Province from the city code prefix (e.g. "qc-13" → "QC")
            province = city_id.split("-")[0].upper() if "-" in city_id else ""

            # Extract coordinates from the URL field (coords=lat,lon)
            lat = None
            lon = None
            url_str = (props.get("url") or {}).get("en", "")
            match = _COORDS_RE.search(url_str)
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))

            matches.append({
                "id": city_id,
                "name": name,
                "province": province,
                "lat": lat,
                "lon": lon,
            })

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
        """Find the nearest AQHI forecast station within ±1.5° of the city."""
        bbox = f"{lon - 1.5:.1f},{lat - 1.5:.1f},{lon + 1.5:.1f},{lat + 1.5:.1f}"
        url = (
            f"{EC_API_BASE}/collections/aqhi-forecasts-realtime/items"
            f"?f=json&bbox={bbox}&limit=200&skipGeometry=true"
            f"&properties=location_id,location_name_en"
        )
        session = async_get_clientsession(self.hass)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("AQHI discovery failed: %s", err)
            return None

        features = data.get("features") or []
        if not features:
            return None

        # Deduplicate by location_id (many features per station)
        stations: dict[str, dict] = {}
        for f in features:
            props = f.get("properties") or {}
            loc_id = props.get("location_id")
            if loc_id and loc_id not in stations:
                # AQHI features don't have coordinates in properties —
                # we just pick the nearest by location_id.
                # EC AQHI stations are sparse enough that bbox filtering
                # plus first-seen is sufficient.
                stations[loc_id] = {
                    "location_id": loc_id,
                    "name": props.get("location_name_en", loc_id),
                }

        if not stations:
            return None

        # If we only have one station, return it
        if len(stations) == 1:
            return next(iter(stations.values()))["location_id"]

        # With multiple stations, just return the first one (bbox already limits to nearby)
        # In practice, most regions have 1-2 AQHI stations
        return next(iter(stations.values()))["location_id"]

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
