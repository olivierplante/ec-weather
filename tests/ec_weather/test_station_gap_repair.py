"""Tests for the station-data-gap repair (existing installs on incomplete
citypages that predate the onboarding station_choice step).

Covers:
  - ECWeatherCoordinator surfacing ``station_missing`` from the raw citypage
    props (Part A).
  - The pure predicate ``should_offer_station_gap_repair`` (Part B).
  - Issue creation/deletion via ``async_manage_station_gap_issue``.
  - The ``StationGapRepairFlow`` keep and switch paths.

Synthetic data only: coords 45.5017,-73.5673, city codes/names made up
(qc-68/TestVille, qc-99/TestCity) — never real personal locations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from ec_weather.api_client import AqhiDiscoveryError
from ec_weather.config_flow import (
    STATION_CHOICE_KEEP,
    STATION_CHOICE_SWITCH,
    _compute_alert_bbox,
    _compute_geomet_bbox,
)
from ec_weather.const import (
    CONF_AQHI_LOCATION_ID,
    CONF_BBOX,
    CONF_CITY_CODE,
    CONF_CITY_NAME,
    CONF_GEOMET_BBOX,
    CONF_LANGUAGE,
    CONF_LAT,
    CONF_LON,
    CONF_STATION_GAP_DISMISSED_FOR,
    DOMAIN,
)
from ec_weather.coordinator import ECWeatherCoordinator
from ec_weather.repairs import (
    STATION_GAP_ISSUE_ID,
    StationGapRepairFlow,
    async_manage_station_gap_issue,
    should_offer_station_gap_repair,
)

from .conftest import load_fixture

_LAT = 45.5017
_LON = -73.5673


def _make_entry(**data_overrides) -> MagicMock:
    """A minimal config-entry double carrying entry data for repairs.py."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_CITY_CODE: "qc-68",
        CONF_CITY_NAME: "TestVille",
        CONF_LANGUAGE: "en",
        CONF_LAT: _LAT,
        CONF_LON: _LON,
        CONF_BBOX: "old-bbox",
        CONF_GEOMET_BBOX: "old-geomet-bbox",
        CONF_AQHI_LOCATION_ID: "OLD-AQHI",
        **data_overrides,
    }
    entry.options = {}
    return entry


# ---------------------------------------------------------------------------
# Part A — coordinator surfaces missing_data_points as "station_missing"
# ---------------------------------------------------------------------------

class TestStationMissingSurfacedByCoordinator:
    async def test_auto_station_fixture_reports_missing_sky_condition(
        self, hass: HomeAssistant, aioclient_mock
    ):
        """The base fixture is itself an auto-station response (condition
        null, iconCode carries no value) → station_missing == ["sky_condition"]."""
        data = load_fixture("citypage_weather.json")
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/on-118?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = ECWeatherCoordinator(hass, city_code="on-118", language="en")
        result = await coord._async_update_data()

        assert result["station_missing"] == ["sky_condition"]

    async def test_complete_fixture_reports_no_missing_points(
        self, hass: HomeAssistant, aioclient_mock
    ):
        data = load_fixture("citypage_weather.json")
        cc = data["properties"]["currentConditions"]
        cc["condition"] = {"en": "Sunny", "fr": "Ensoleillé"}
        cc["iconCode"] = {
            "format": "png", "value": 0,
            "url": "https://weather.gc.ca/weathericons/00.gif",
        }
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/on-118?f=json&lang=en&skipGeometry=true",
            json=data,
        )

        coord = ECWeatherCoordinator(hass, city_code="on-118", language="en")
        result = await coord._async_update_data()

        assert result["station_missing"] == []


# ---------------------------------------------------------------------------
# Part B — pure predicate
# ---------------------------------------------------------------------------

class TestShouldOfferStationGapRepair:
    def test_offers_when_missing_and_no_dismissal(self):
        data = {CONF_CITY_CODE: "qc-68"}
        assert should_offer_station_gap_repair(data, ["sky_condition"]) is True

    def test_not_offered_when_dismissed_for_same_city(self):
        data = {CONF_CITY_CODE: "qc-68", CONF_STATION_GAP_DISMISSED_FOR: "qc-68"}
        assert should_offer_station_gap_repair(data, ["sky_condition"]) is False

    def test_offered_when_dismissed_for_a_different_city(self):
        """User switched city since dismissing → repair re-arms."""
        data = {CONF_CITY_CODE: "qc-68", CONF_STATION_GAP_DISMISSED_FOR: "on-118"}
        assert should_offer_station_gap_repair(data, ["sky_condition"]) is True

    def test_not_offered_when_no_missing_points(self):
        data = {CONF_CITY_CODE: "qc-68"}
        assert should_offer_station_gap_repair(data, []) is False


# ---------------------------------------------------------------------------
# Issue registry management
# ---------------------------------------------------------------------------

class TestAsyncManageStationGapIssue:
    async def test_creates_issue_when_predicate_true(self, hass: HomeAssistant):
        entry = _make_entry()

        async_manage_station_gap_issue(hass, entry, ["sky_condition"])

        issue = ir.async_get(hass).async_get_issue(DOMAIN, STATION_GAP_ISSUE_ID)
        assert issue is not None
        assert issue.translation_placeholders["city_name"] == "TestVille"
        assert "sky condition" in issue.translation_placeholders["missing_points"]

    async def test_deletes_issue_when_predicate_false(self, hass: HomeAssistant):
        entry = _make_entry()
        async_manage_station_gap_issue(hass, entry, ["sky_condition"])
        assert ir.async_get(hass).async_get_issue(DOMAIN, STATION_GAP_ISSUE_ID) is not None

        async_manage_station_gap_issue(hass, entry, [])

        assert ir.async_get(hass).async_get_issue(DOMAIN, STATION_GAP_ISSUE_ID) is None


# ---------------------------------------------------------------------------
# StationGapRepairFlow — keep path
# ---------------------------------------------------------------------------

class TestStationGapRepairFlowKeep:
    async def test_keep_sets_dismissed_for_current_city_and_does_not_reload(
        self, hass: HomeAssistant
    ):
        entry = _make_entry()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        flow = StationGapRepairFlow(entry, ["sky_condition"])
        flow.hass = hass

        with patch(
            "ec_weather.repairs.find_nearest_complete_city",
            AsyncMock(return_value=None),
        ):
            await flow.async_step_init()
            result = await flow.async_step_choose({"choice": STATION_CHOICE_KEEP})

        hass.config_entries.async_update_entry.assert_called_once()
        call = hass.config_entries.async_update_entry.call_args
        new_data = call.kwargs["data"]
        assert new_data[CONF_STATION_GAP_DISMISSED_FOR] == "qc-68"
        # keep path is a pure config-entry-data edit — no reload needed.
        hass.config_entries.async_reload.assert_not_called()
        assert result["type"] == "create_entry"


# ---------------------------------------------------------------------------
# StationGapRepairFlow — switch path
# ---------------------------------------------------------------------------

class TestStationGapRepairFlowSwitch:
    _ALTERNATIVE = {
        "id": "qc-99",
        "name": "TestCity",
        "lat": 45.6,
        "lon": -73.6,
        "distance_km": 12,
    }

    async def test_switch_updates_city_bboxes_aqhi_and_reloads(
        self, hass: HomeAssistant
    ):
        entry = _make_entry(**{CONF_STATION_GAP_DISMISSED_FOR: "qc-68"})
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        flow = StationGapRepairFlow(entry, ["sky_condition"])
        flow.hass = hass

        with patch(
            "ec_weather.repairs.find_nearest_complete_city",
            AsyncMock(return_value=self._ALTERNATIVE),
        ), patch(
            "ec_weather.repairs.discover_aqhi_station",
            AsyncMock(return_value="NEW-AQHI"),
        ):
            await flow.async_step_init()
            result = await flow.async_step_choose({"choice": STATION_CHOICE_SWITCH})

        hass.config_entries.async_update_entry.assert_called_once()
        call = hass.config_entries.async_update_entry.call_args
        new_data = call.kwargs["data"]
        assert new_data[CONF_CITY_CODE] == "qc-99"
        assert new_data[CONF_CITY_NAME] == "TestCity"
        assert new_data[CONF_LAT] == 45.6
        assert new_data[CONF_LON] == -73.6
        assert new_data[CONF_BBOX] == _compute_alert_bbox(45.6, -73.6)
        assert new_data[CONF_GEOMET_BBOX] == _compute_geomet_bbox(45.6, -73.6)
        assert new_data[CONF_AQHI_LOCATION_ID] == "NEW-AQHI"
        assert CONF_STATION_GAP_DISMISSED_FOR not in new_data

        hass.config_entries.async_reload.assert_called_once_with("test_entry")
        assert result["type"] == "create_entry"

    async def test_switch_with_aqhi_discovery_none_keeps_old_aqhi_id(
        self, hass: HomeAssistant
    ):
        entry = _make_entry()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        flow = StationGapRepairFlow(entry, ["sky_condition"])
        flow.hass = hass

        with patch(
            "ec_weather.repairs.find_nearest_complete_city",
            AsyncMock(return_value=self._ALTERNATIVE),
        ), patch(
            "ec_weather.repairs.discover_aqhi_station",
            AsyncMock(return_value=None),
        ):
            await flow.async_step_init()
            result = await flow.async_step_choose({"choice": STATION_CHOICE_SWITCH})

        call = hass.config_entries.async_update_entry.call_args
        new_data = call.kwargs["data"]
        assert new_data[CONF_AQHI_LOCATION_ID] == "OLD-AQHI"
        assert result["type"] == "create_entry"

    async def test_switch_with_aqhi_discovery_network_error_keeps_old_aqhi_id(
        self, hass: HomeAssistant
    ):
        """FIX 1 call site: a network error from discover_aqhi_station (now
        signaled via AqhiDiscoveryError) must behave exactly like a "no
        station found" answer here — old AQHI id kept, no crash."""
        entry = _make_entry()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        flow = StationGapRepairFlow(entry, ["sky_condition"])
        flow.hass = hass

        with patch(
            "ec_weather.repairs.find_nearest_complete_city",
            AsyncMock(return_value=self._ALTERNATIVE),
        ), patch(
            "ec_weather.repairs.discover_aqhi_station",
            AsyncMock(side_effect=AqhiDiscoveryError("boom")),
        ):
            await flow.async_step_init()
            result = await flow.async_step_choose({"choice": STATION_CHOICE_SWITCH})

        call = hass.config_entries.async_update_entry.call_args
        new_data = call.kwargs["data"]
        assert new_data[CONF_AQHI_LOCATION_ID] == "OLD-AQHI"
        assert result["type"] == "create_entry"
