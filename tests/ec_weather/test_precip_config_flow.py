"""Tests for the precip-station selection step (issue #9, Part B).

The config/options/repair flows all present the same choice: the nearest
reporting station and (when the nearest is combined-only) the nearest
split-capable station, each labelled with name + distance + data type,
plus an explicit opt-out. ``build_precip_choices`` is the pure builder
that turns a discovery result into selectable options and a value→station
lookup, so the labelling/opt-out logic is testable without a flow.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant

from ec_weather.config_flow import (
    PRECIP_OPT_OUT,
    ECWeatherConfigFlow,
    build_precip_choices,
    precip_default_choice,
)
from ec_weather.const import (
    CONF_CITY_NAME,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_PRECIP_DISCOVERED,
    CONF_PRECIP_STATION_ID,
    CONF_PRECIP_STATION_TYPE,
)


def _station(sid, name, stype, dist):
    return {
        "station_id": sid,
        "name": name,
        "type": stype,
        "distance_km": dist,
        "lat": 45.0,
        "lon": -74.0,
    }


class TestBuildPrecipChoices:
    def test_opt_out_always_present_and_last(self):
        discovery = {"nearest": None, "nearest_split": None}
        options, mapping = build_precip_choices(discovery, "en")
        assert options[-1]["value"] == PRECIP_OPT_OUT
        assert PRECIP_OPT_OUT in mapping
        assert mapping[PRECIP_OPT_OUT] is None

    def test_no_stations_only_opt_out(self):
        discovery = {"nearest": None, "nearest_split": None}
        options, mapping = build_precip_choices(discovery, "en")
        assert len(options) == 1

    def test_combined_nearest_offers_both_when_split_differs(self):
        discovery = {
            "nearest": _station("C", "Combo Near", "combined", 12.0),
            "nearest_split": _station("S", "Split Far", "split", 35.0),
        }
        options, mapping = build_precip_choices(discovery, "en")
        values = [o["value"] for o in options]
        assert "C" in values and "S" in values
        assert mapping["C"]["station_id"] == "C"
        assert mapping["S"]["station_id"] == "S"
        # opt-out + 2 stations
        assert len(options) == 3

    def test_no_duplicate_when_nearest_is_split(self):
        """If nearest == nearest_split, the station appears once."""
        split = _station("S", "Split Near", "split", 8.0)
        discovery = {"nearest": split, "nearest_split": split}
        options, mapping = build_precip_choices(discovery, "en")
        station_values = [o["value"] for o in options if o["value"] != PRECIP_OPT_OUT]
        assert station_values == ["S"]

    def test_label_includes_distance_and_type(self):
        discovery = {
            "nearest": _station("C", "Combo Near", "combined", 12.3),
            "nearest_split": None,
        }
        options, _ = build_precip_choices(discovery, "en")
        label = options[0]["label"]
        assert "Combo Near" in label
        assert "12" in label  # distance shown


class TestPrecipDefaultChoice:
    """The reconfigure form pre-selects the currently configured station."""

    def _options(self):
        discovery = {
            "nearest": _station("C", "Combo", "combined", 12.0),
            "nearest_split": _station("S", "Split", "split", 35.0),
        }
        options, _ = build_precip_choices(discovery, "en")
        return options

    def test_pre_selects_current_station_when_in_options(self):
        assert precip_default_choice(self._options(), "S") == "S"

    def test_opt_out_default_when_none_configured(self):
        assert precip_default_choice(self._options(), None) == PRECIP_OPT_OUT

    def test_opt_out_default_when_current_not_in_options(self):
        """Configured station no longer discovered → fall back to opt-out."""
        assert precip_default_choice(self._options(), "GONE") == PRECIP_OPT_OUT


def _flow_with_pending(hass, station=None):
    flow = ECWeatherConfigFlow()
    flow.hass = hass
    flow._pending_entry_data = {
        "city_code": "on-118",
        CONF_CITY_NAME: "Ottawa",
        CONF_LANGUAGE: "en",
        CONF_LAT: 45.42,
        CONF_LON: -75.70,
    }
    return flow


class TestPrecipStep:
    @patch("ec_weather.config_flow.discover_precip_stations")
    async def test_no_station_auto_skips_to_entry(
        self, mock_discover, hass: HomeAssistant
    ) -> None:
        """No nearby station → step auto-creates entry without a station."""
        mock_discover.return_value = {"nearest": None, "nearest_split": None}
        flow = _flow_with_pending(hass)
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        await flow.async_step_precip(user_input=None)

        data = flow.async_create_entry.call_args[1]["data"]
        assert CONF_PRECIP_STATION_ID not in data
        assert data[CONF_PRECIP_DISCOVERED] is True

    @patch("ec_weather.config_flow.discover_precip_stations")
    async def test_station_shows_form_then_stores_selection(
        self, mock_discover, hass: HomeAssistant
    ) -> None:
        """A discovered station produces a form; choosing it stores the fields."""
        mock_discover.return_value = {
            "nearest": _station("7025251", "Trudeau", "split", 34.0),
            "nearest_split": _station("7025251", "Trudeau", "split", 34.0),
        }
        flow = _flow_with_pending(hass)

        form = await flow.async_step_precip(user_input=None)
        assert form["type"] == "form"
        assert form["step_id"] == "precip"

        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        await flow.async_step_precip(
            user_input={CONF_PRECIP_STATION_ID: "7025251"}
        )
        data = flow.async_create_entry.call_args[1]["data"]
        assert data[CONF_PRECIP_STATION_ID] == "7025251"
        assert data[CONF_PRECIP_STATION_TYPE] == "split"

    @patch("ec_weather.config_flow.discover_precip_stations")
    async def test_opt_out_stores_no_station(
        self, mock_discover, hass: HomeAssistant
    ) -> None:
        """Selecting the opt-out leaves no station configured."""
        mock_discover.return_value = {
            "nearest": _station("C", "Combo", "combined", 10.0),
            "nearest_split": None,
        }
        flow = _flow_with_pending(hass)
        await flow.async_step_precip(user_input=None)  # populates choices

        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        await flow.async_step_precip(
            user_input={CONF_PRECIP_STATION_ID: PRECIP_OPT_OUT}
        )
        data = flow.async_create_entry.call_args[1]["data"]
        assert CONF_PRECIP_STATION_ID not in data
        assert data[CONF_PRECIP_DISCOVERED] is True
