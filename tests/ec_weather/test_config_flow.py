"""Tests for EC Weather config flow and options flow.

Covers:
- Pure helper functions (_compute_alert_bbox, _compute_geomet_bbox)
- Config flow steps (user, select_city, confirm)
- Options flow (async_step_init)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from ec_weather.config_flow import (
    ECWeatherConfigFlow,
    ECWeatherOptionsFlow,
    _compute_alert_bbox,
    _compute_geomet_bbox,
)
from ec_weather.const import (
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
    POLLING_MODE_EFFICIENT,
    SUPPORTED_LANGUAGES,
)


# ---------------------------------------------------------------------------
# Existing constants tests (preserved)
# ---------------------------------------------------------------------------

class TestOptionsConstants:
    def test_supported_languages(self):
        """Integration supports English and French."""
        assert "en" in SUPPORTED_LANGUAGES
        assert "fr" in SUPPORTED_LANGUAGES

    def test_default_language_is_english(self):
        """Default language is English."""
        assert DEFAULT_LANGUAGE == "en"

    def test_config_keys_defined(self):
        """All required config keys are defined as constants."""
        assert CONF_CITY_CODE == "city_code"
        assert CONF_LANGUAGE == "language"
        assert CONF_BBOX == "bbox"
        assert CONF_GEOMET_BBOX == "geomet_bbox"
        assert CONF_AQHI_LOCATION_ID == "aqhi_location_id"


# ---------------------------------------------------------------------------
# Pure function tests: _compute_alert_bbox
# ---------------------------------------------------------------------------

class TestComputeAlertBbox:
    """Tests for _compute_alert_bbox — pure function, no HA needed."""

    def test_basic_positive_coords(self):
        """Returns lon-0.2,lat-0.2,lon+0.2,lat+0.2 format."""
        result = _compute_alert_bbox(45.0, -74.0)
        assert result == "-74.2,44.8,-73.8,45.2"

    def test_format_has_one_decimal(self):
        """Values are formatted with one decimal place."""
        result = _compute_alert_bbox(45.42, -75.70)
        # lon-0.2 = -74.27, lat-0.2 = 45.58, lon+0.2 = -73.87, lat+0.2 = 45.98
        assert result == "-74.3,45.6,-73.9,46.0"

    def test_zero_coordinates(self):
        """Works for (0, 0) — equator/prime meridian."""
        result = _compute_alert_bbox(0.0, 0.0)
        assert result == "-0.2,-0.2,0.2,0.2"

    def test_high_latitude(self):
        """Works for high-latitude locations."""
        result = _compute_alert_bbox(82.5, -62.3)
        assert result == "-62.5,82.3,-62.1,82.7"

    def test_negative_lat_and_lon(self):
        """Works for southern/western hemisphere coordinates."""
        result = _compute_alert_bbox(-33.9, -18.4)
        assert result == "-18.6,-34.1,-18.2,-33.7"


# ---------------------------------------------------------------------------
# Pure function tests: _compute_geomet_bbox
# ---------------------------------------------------------------------------

class TestComputeGeoMetBbox:
    """Tests for _compute_geomet_bbox — pure function, no HA needed."""

    def test_basic_positive_coords(self):
        """Returns lat-1.0,lon-1.0,lat+1.0,lon+1.0 format (EPSG:4326 axis order)."""
        result = _compute_geomet_bbox(45.0, -74.0)
        assert result == "44.000,-75.000,46.000,-73.000"

    def test_format_has_three_decimals(self):
        """Values are formatted with three decimal places."""
        result = _compute_geomet_bbox(45.42, -75.70)
        assert result == "44.420,-76.700,46.420,-74.700"

    def test_zero_coordinates(self):
        """Works for (0, 0) — equator/prime meridian."""
        result = _compute_geomet_bbox(0.0, 0.0)
        assert result == "-1.000,-1.000,1.000,1.000"

    def test_axis_order_is_lat_lon(self):
        """EPSG:4326 WMS 1.3.0: first pair is lat, second is lon."""
        result = _compute_geomet_bbox(50.0, -100.0)
        parts = result.split(",")
        # First value should be lat - 1.0 = 49.000
        assert parts[0] == "49.000"
        # Second value should be lon - 1.0 = -101.000
        assert parts[1] == "-101.000"
        # Third value should be lat + 1.0 = 51.000
        assert parts[2] == "51.000"
        # Fourth value should be lon + 1.0 = -99.000
        assert parts[3] == "-99.000"


# ---------------------------------------------------------------------------
# Helpers for config flow tests
# ---------------------------------------------------------------------------

SAINT_JEROME_CITY = {
    "id": "on-118",
    "name": "Ottawa",
    "province": "QC",
    "lat": 45.42,
    "lon": -75.70,
}

MONTREAL_CITY = {
    "id": "qc-147",
    "name": "Montréal",
    "province": "QC",
    "lat": 45.51,
    "lon": -73.59,
}


def _make_flow(hass: HomeAssistant) -> ECWeatherConfigFlow:
    """Create an ECWeatherConfigFlow attached to a hass instance."""
    flow = ECWeatherConfigFlow()
    flow.hass = hass
    # Mock _async_current_entries to return empty by default (no duplicates)
    flow._async_current_entries = MagicMock(return_value=[])
    return flow


# ---------------------------------------------------------------------------
# Config flow: async_step_user
# ---------------------------------------------------------------------------

class TestAsyncStepUser:
    """Tests for ECWeatherConfigFlow.async_step_user."""

    async def test_shows_form_on_first_load(self, hass: HomeAssistant) -> None:
        """First load (no user_input) shows the user form."""
        flow = _make_flow(hass)
        with patch.object(flow, "_auto_detect_city", return_value=None):
            result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"

    async def test_empty_city_query_shows_error(self, hass: HomeAssistant) -> None:
        """Submitting an empty city_query shows no_city_name error."""
        flow = _make_flow(hass)
        result = await flow.async_step_user(
            user_input={"city_query": "", CONF_LANGUAGE: "en"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["city_query"] == "no_city_name"

    async def test_whitespace_only_city_query_shows_error(
        self, hass: HomeAssistant,
    ) -> None:
        """Submitting whitespace-only city_query shows no_city_name error."""
        flow = _make_flow(hass)
        result = await flow.async_step_user(
            user_input={"city_query": "   ", CONF_LANGUAGE: "en"}
        )

        assert result["type"] == "form"
        assert result["errors"]["city_query"] == "no_city_name"

    async def test_single_match_proceeds_to_confirm(
        self, hass: HomeAssistant,
    ) -> None:
        """Single city match skips disambiguation and proceeds to confirm."""
        flow = _make_flow(hass)
        with patch.object(
            flow, "_search_cities", return_value=[SAINT_JEROME_CITY.copy()]
        ), patch.object(flow, "_run_discovery") as mock_discovery:
            mock_discovery.return_value = {"type": "form", "step_id": "confirm"}
            result = await flow.async_step_user(
                user_input={"city_query": "Ottawa", CONF_LANGUAGE: "en"}
            )

        assert result["step_id"] == "confirm"
        assert flow._selected_city["id"] == "on-118"
        assert flow._selected_city["language"] == "en"

    async def test_multiple_matches_go_to_select_city(
        self, hass: HomeAssistant,
    ) -> None:
        """Multiple matches proceed to select_city disambiguation step."""
        flow = _make_flow(hass)
        cities = [SAINT_JEROME_CITY.copy(), MONTREAL_CITY.copy()]
        with patch.object(flow, "_search_cities", return_value=cities):
            result = await flow.async_step_user(
                user_input={"city_query": "Saint", CONF_LANGUAGE: "en"}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "select_city"
        assert len(flow._cities) == 2

    async def test_no_matches_shows_error(self, hass: HomeAssistant) -> None:
        """Zero city matches shows no_city_found error."""
        flow = _make_flow(hass)
        with patch.object(flow, "_search_cities", return_value=[]):
            result = await flow.async_step_user(
                user_input={"city_query": "Nonexistent", CONF_LANGUAGE: "en"}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["city_query"] == "no_city_found"

    async def test_api_error_shows_error(self, hass: HomeAssistant) -> None:
        """aiohttp.ClientError during search shows api_error."""
        flow = _make_flow(hass)
        with patch.object(
            flow, "_search_cities", side_effect=aiohttp.ClientError("boom")
        ):
            result = await flow.async_step_user(
                user_input={"city_query": "Montréal", CONF_LANGUAGE: "en"}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["city_query"] == "api_error"

    async def test_timeout_error_shows_api_error(
        self, hass: HomeAssistant,
    ) -> None:
        """asyncio.TimeoutError during search shows api_error."""
        flow = _make_flow(hass)
        with patch.object(
            flow, "_search_cities", side_effect=asyncio.TimeoutError()
        ):
            result = await flow.async_step_user(
                user_input={"city_query": "Montréal", CONF_LANGUAGE: "en"}
            )

        assert result["type"] == "form"
        assert result["errors"]["city_query"] == "api_error"

    async def test_already_configured_aborts(self, hass: HomeAssistant) -> None:
        """If an entry already exists, the flow aborts."""
        flow = _make_flow(hass)
        flow._async_current_entries = MagicMock(return_value=[MagicMock()])

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"

    async def test_french_language_passed_to_search(
        self, hass: HomeAssistant,
    ) -> None:
        """Language selection is passed to _search_cities and stored on selected city."""
        flow = _make_flow(hass)
        city = {**SAINT_JEROME_CITY, "name": "Ottawa"}
        with patch.object(
            flow, "_search_cities", return_value=[city]
        ) as mock_search, patch.object(flow, "_run_discovery") as mock_disc:
            mock_disc.return_value = {"type": "form", "step_id": "confirm"}
            await flow.async_step_user(
                user_input={"city_query": "Ottawa", CONF_LANGUAGE: "fr"}
            )

        mock_search.assert_called_once_with("Ottawa", "fr")
        assert flow._selected_city["language"] == "fr"


# ---------------------------------------------------------------------------
# Config flow: async_step_select_city
# ---------------------------------------------------------------------------

class TestAsyncStepSelectCity:
    """Tests for ECWeatherConfigFlow.async_step_select_city."""

    async def test_shows_form_with_no_input(self, hass: HomeAssistant) -> None:
        """With no user_input, shows the disambiguation form."""
        flow = _make_flow(hass)
        flow._cities = [SAINT_JEROME_CITY.copy(), MONTREAL_CITY.copy()]
        flow._cities_language = "en"

        result = await flow.async_step_select_city(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "select_city"

    async def test_selecting_city_proceeds_to_discovery(
        self, hass: HomeAssistant,
    ) -> None:
        """Selecting a city ID from the list triggers discovery and confirm."""
        flow = _make_flow(hass)
        flow._cities = [SAINT_JEROME_CITY.copy(), MONTREAL_CITY.copy()]
        flow._cities_language = "en"

        with patch.object(flow, "_run_discovery") as mock_discovery:
            mock_discovery.return_value = {"type": "form", "step_id": "confirm"}
            result = await flow.async_step_select_city(
                user_input={"city_id": "qc-147"}
            )

        assert result["step_id"] == "confirm"
        assert flow._selected_city["id"] == "qc-147"
        assert flow._selected_city["name"] == "Montréal"
        assert flow._selected_city["language"] == "en"

    async def test_selecting_city_sets_language(
        self, hass: HomeAssistant,
    ) -> None:
        """Selected city gets the language from the original search."""
        flow = _make_flow(hass)
        flow._cities = [SAINT_JEROME_CITY.copy()]
        flow._cities_language = "fr"

        with patch.object(flow, "_run_discovery") as mock_discovery:
            mock_discovery.return_value = {"type": "form", "step_id": "confirm"}
            await flow.async_step_select_city(
                user_input={"city_id": "on-118"}
            )

        assert flow._selected_city["language"] == "fr"


# ---------------------------------------------------------------------------
# Config flow: async_step_confirm
# ---------------------------------------------------------------------------

class TestAsyncStepConfirm:
    """Tests for ECWeatherConfigFlow.async_step_confirm."""

    async def test_shows_form_with_no_input(self, hass: HomeAssistant) -> None:
        """With no user_input, shows pre-filled confirmation form."""
        flow = _make_flow(hass)
        flow._selected_city = {**SAINT_JEROME_CITY, "language": "en"}
        flow._discovered_aqhi = "AQHI-123"

        result = await flow.async_step_confirm(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "confirm"
        # Description placeholders should contain city info
        assert result["description_placeholders"]["city_name"] == "Ottawa"
        assert result["description_placeholders"]["province"] == "QC"
        assert result["description_placeholders"]["city_code"] == "on-118"

    async def test_creates_entry_with_user_input(
        self, hass: HomeAssistant,
    ) -> None:
        """Submitting confirm form creates a config entry with correct data."""
        flow = _make_flow(hass)
        flow._selected_city = {**SAINT_JEROME_CITY, "language": "en"}
        flow._discovered_aqhi = None

        # Mock async_create_entry so we can inspect the call
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        user_input = {
            CONF_LAT: 45.42,
            CONF_LON: -75.70,
            CONF_BBOX: "-74.3,45.6,-73.9,46.0",
            CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
            CONF_AQHI_LOCATION_ID: "AQHI-456",
        }
        result = await flow.async_step_confirm(user_input=user_input)

        assert result["type"] == "create_entry"
        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args[1]

        assert call_kwargs["title"] == "Ottawa"
        data = call_kwargs["data"]
        assert data[CONF_CITY_CODE] == "on-118"
        assert data[CONF_CITY_NAME] == "Ottawa"
        assert data[CONF_LANGUAGE] == "en"
        assert data[CONF_LAT] == 45.42
        assert data[CONF_LON] == -75.70
        assert data[CONF_BBOX] == "-74.3,45.6,-73.9,46.0"
        assert data[CONF_GEOMET_BBOX] == "44.420,-76.700,46.420,-74.700"
        assert data[CONF_AQHI_LOCATION_ID] == "AQHI-456"

    async def test_empty_aqhi_stored_as_none(
        self, hass: HomeAssistant,
    ) -> None:
        """Empty string AQHI location is stored as None."""
        flow = _make_flow(hass)
        flow._selected_city = {**SAINT_JEROME_CITY, "language": "en"}
        flow._discovered_aqhi = None

        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        user_input = {
            CONF_LAT: 45.42,
            CONF_LON: -75.70,
            CONF_BBOX: "-74.3,45.6,-73.9,46.0",
            CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
            CONF_AQHI_LOCATION_ID: "",
        }
        await flow.async_step_confirm(user_input=user_input)

        data = flow.async_create_entry.call_args[1]["data"]
        assert data[CONF_AQHI_LOCATION_ID] is None

    async def test_confirm_uses_city_id_as_title_fallback(
        self, hass: HomeAssistant,
    ) -> None:
        """If city has no name, title falls back to city id."""
        flow = _make_flow(hass)
        flow._selected_city = {"id": "qc-99", "language": "en"}
        flow._discovered_aqhi = None

        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        user_input = {
            CONF_LAT: 46.0,
            CONF_LON: -73.0,
            CONF_BBOX: "-73.2,45.8,-72.8,46.2",
            CONF_GEOMET_BBOX: "45.000,-75.700,47.000,-72.000",
            CONF_AQHI_LOCATION_ID: "",
        }
        await flow.async_step_confirm(user_input=user_input)

        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["title"] == "qc-99"

    async def test_city_without_coords_defaults_to_zero(
        self, hass: HomeAssistant,
    ) -> None:
        """City with None lat/lon defaults to 0.0 for bbox computation."""
        flow = _make_flow(hass)
        flow._selected_city = {
            "id": "qc-99",
            "name": "NoCoords",
            "lat": None,
            "lon": None,
            "language": "en",
        }
        flow._discovered_aqhi = None

        result = await flow.async_step_confirm(user_input=None)

        assert result["type"] == "form"
        # Verify defaults use 0.0 for lat/lon
        schema = result["data_schema"]
        schema_dict = dict(schema.schema)
        # The schema keys are vol.Required/Optional with default values
        for key in schema_dict:
            if hasattr(key, "schema") and key.schema == CONF_LAT:
                assert key.default() == 0.0
            if hasattr(key, "schema") and key.schema == CONF_LON:
                assert key.default() == 0.0


# ---------------------------------------------------------------------------
# Config flow: _run_discovery
# ---------------------------------------------------------------------------

class TestRunDiscovery:
    """Tests for ECWeatherConfigFlow._run_discovery."""

    async def test_discovery_with_valid_coords(
        self, hass: HomeAssistant,
    ) -> None:
        """With valid lat/lon, _discover_aqhi_station is called."""
        flow = _make_flow(hass)
        flow._selected_city = {**SAINT_JEROME_CITY, "language": "en"}

        with patch.object(
            flow, "_discover_aqhi_station", return_value="AQHI-FOUND"
        ) as mock_aqhi, patch.object(flow, "async_step_confirm") as mock_confirm:
            mock_confirm.return_value = {"type": "form", "step_id": "confirm"}
            await flow._run_discovery()

        mock_aqhi.assert_called_once_with(45.42, -75.70)
        assert flow._discovered_aqhi == "AQHI-FOUND"

    async def test_discovery_without_coords_skips_aqhi(
        self, hass: HomeAssistant,
    ) -> None:
        """Without coordinates, AQHI discovery is skipped."""
        flow = _make_flow(hass)
        flow._selected_city = {
            "id": "qc-99",
            "name": "NoCoords",
            "lat": None,
            "lon": None,
            "language": "en",
        }

        with patch.object(
            flow, "_discover_aqhi_station"
        ) as mock_aqhi, patch.object(flow, "async_step_confirm") as mock_confirm:
            mock_confirm.return_value = {"type": "form", "step_id": "confirm"}
            await flow._run_discovery()

        mock_aqhi.assert_not_called()
        assert flow._discovered_aqhi is None


# ---------------------------------------------------------------------------
# Options flow: async_step_init
# ---------------------------------------------------------------------------

class TestOptionsFlowInit:
    """Tests for ECWeatherOptionsFlow.async_step_init."""

    async def _make_options_flow(
        self,
        hass: HomeAssistant,
        data: dict | None = None,
        options: dict | None = None,
    ) -> ECWeatherOptionsFlow:
        """Create an ECWeatherOptionsFlow with a real config entry registered in hass.

        Uses a real MockConfigEntry so the options flow can look up the entry
        via self.config_entry (which uses self.handler / entry_id internally).
        """
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            title="Ottawa",
            data=data or {
                CONF_CITY_CODE: "on-118",
                CONF_CITY_NAME: "Ottawa",
                CONF_LANGUAGE: "en",
                CONF_BBOX: "-74.3,45.6,-73.9,46.0",
                CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
                CONF_AQHI_LOCATION_ID: None,
            },
            options=options or {},
        )
        entry.add_to_hass(hass)

        flow = ECWeatherOptionsFlow()
        flow.hass = hass
        flow.handler = entry.entry_id

        return flow

    async def test_shows_form_with_no_input(
        self, hass: HomeAssistant,
    ) -> None:
        """With no user_input, shows the options form."""
        flow = await self._make_options_flow(hass)

        result = await flow.async_step_init(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        assert result["description_placeholders"]["city_name"] == "Ottawa"
        assert result["description_placeholders"]["city_code"] == "on-118"

    async def test_mutable_keys_go_to_options(
        self, hass: HomeAssistant,
    ) -> None:
        """Mutable keys (polling_mode, intervals) are saved to options, not data."""
        flow = await self._make_options_flow(hass)

        # Mock async_update_entry and async_reload
        hass.config_entries = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        user_input = {
            CONF_CITY_CODE: "on-118",
            CONF_LANGUAGE: "en",
            CONF_BBOX: "-74.3,45.6,-73.9,46.0",
            CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
            CONF_AQHI_LOCATION_ID: "",
            CONF_POLLING_MODE: POLLING_MODE_EFFICIENT,
            CONF_WEATHER_INTERVAL: 45,
            CONF_AQHI_INTERVAL: 120,
            CONF_WEONG_INTERVAL: 240,
        }
        await flow.async_step_init(user_input=user_input)

        # Check async_update_entry was called
        hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = hass.config_entries.async_update_entry.call_args[1]

        # Mutable keys must be in options
        new_options = call_kwargs["options"]
        assert new_options[CONF_POLLING_MODE] == POLLING_MODE_EFFICIENT
        assert new_options[CONF_WEATHER_INTERVAL] == 45
        assert new_options[CONF_AQHI_INTERVAL] == 120
        assert new_options[CONF_WEONG_INTERVAL] == 240

        # Immutable keys must be in data
        new_data = call_kwargs["data"]
        assert new_data[CONF_CITY_CODE] == "on-118"
        assert new_data[CONF_LANGUAGE] == "en"

    async def test_immutable_keys_go_to_data(
        self, hass: HomeAssistant,
    ) -> None:
        """Immutable keys (city_code, language, bbox, etc.) are saved to data."""
        flow = await self._make_options_flow(hass)

        hass.config_entries = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        user_input = {
            CONF_CITY_CODE: "qc-99",
            CONF_LANGUAGE: "fr",
            CONF_BBOX: "-75.0,45.0,-74.0,46.0",
            CONF_GEOMET_BBOX: "45.000,-75.000,47.000,-73.000",
            CONF_AQHI_LOCATION_ID: "AQHI-NEW",
            CONF_POLLING_MODE: DEFAULT_POLLING_MODE,
            CONF_WEATHER_INTERVAL: DEFAULT_WEATHER_INTERVAL,
            CONF_AQHI_INTERVAL: DEFAULT_AQHI_INTERVAL,
            CONF_WEONG_INTERVAL: DEFAULT_WEONG_INTERVAL,
        }
        await flow.async_step_init(user_input=user_input)

        call_kwargs = hass.config_entries.async_update_entry.call_args[1]
        new_data = call_kwargs["data"]

        assert new_data[CONF_CITY_CODE] == "qc-99"
        assert new_data[CONF_LANGUAGE] == "fr"
        assert new_data[CONF_BBOX] == "-75.0,45.0,-74.0,46.0"
        assert new_data[CONF_GEOMET_BBOX] == "45.000,-75.000,47.000,-73.000"
        assert new_data[CONF_AQHI_LOCATION_ID] == "AQHI-NEW"

    async def test_form_defaults_from_current_options(
        self, hass: HomeAssistant,
    ) -> None:
        """Form defaults read from current entry.options for mutable keys."""
        flow = await self._make_options_flow(
            hass,
            options={
                CONF_POLLING_MODE: POLLING_MODE_EFFICIENT,
                CONF_WEATHER_INTERVAL: 60,
                CONF_AQHI_INTERVAL: 360,
                CONF_WEONG_INTERVAL: 480,
            },
        )

        result = await flow.async_step_init(user_input=None)

        # Extract defaults from the schema
        schema_dict = dict(result["data_schema"].schema)
        defaults = {}
        for key_obj in schema_dict:
            if hasattr(key_obj, "schema") and hasattr(key_obj, "default"):
                defaults[key_obj.schema] = key_obj.default()

        assert defaults[CONF_POLLING_MODE] == POLLING_MODE_EFFICIENT
        assert defaults[CONF_WEATHER_INTERVAL] == 60
        assert defaults[CONF_AQHI_INTERVAL] == 360
        assert defaults[CONF_WEONG_INTERVAL] == 480

    async def test_reloads_entry_after_save(
        self, hass: HomeAssistant,
    ) -> None:
        """Options flow triggers a reload after saving."""
        flow = await self._make_options_flow(hass)
        entry_id = flow.handler

        # Patch only async_reload on the real config entries manager
        with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
            flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

            user_input = {
                CONF_CITY_CODE: "on-118",
                CONF_LANGUAGE: "en",
                CONF_BBOX: "-74.3,45.6,-73.9,46.0",
                CONF_GEOMET_BBOX: "44.420,-76.700,46.420,-74.700",
                CONF_AQHI_LOCATION_ID: "",
                CONF_POLLING_MODE: DEFAULT_POLLING_MODE,
                CONF_WEATHER_INTERVAL: DEFAULT_WEATHER_INTERVAL,
                CONF_AQHI_INTERVAL: DEFAULT_AQHI_INTERVAL,
                CONF_WEONG_INTERVAL: DEFAULT_WEONG_INTERVAL,
            }
            await flow.async_step_init(user_input=user_input)

            mock_reload.assert_awaited_once_with(entry_id)
