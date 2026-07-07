"""Tests for honest stale detection (review finding: last_updated false-positive).

HA only writes a new state object when the value or attributes change, so a
stable temperature makes state.last_updated look hours old across perfectly
successful refreshes. The fix: the coordinator stamps ``fetched_at`` on every
successful EC fetch and the temperature sensor exposes it as an attribute —
the attribute changing forces a state write, so the frontend always sees a
fresh heartbeat while fetches succeed. The card banner then measures real
fetch failures, not value stability.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant

from ec_weather.sensor import CURRENT_SENSOR_DESCRIPTIONS, ECCurrentSensor

from .conftest import CARD_JS_PATH as CARD_JS
from .test_weather_coordinator import _build_ec_response, _make_coordinator


def _description(key: str):
    return next(d for d in CURRENT_SENSOR_DESCRIPTIONS if d.key == key)


class TestCoordinatorHeartbeat:
    async def test_fetched_at_stamped_on_success(self, hass: HomeAssistant, aioclient_mock):
        aioclient_mock.get(
            "https://api.weather.gc.ca/collections/citypageweather-realtime"
            "/items/on-118?f=json&lang=en&skipGeometry=true",
            json=_build_ec_response(),
        )
        coordinator = _make_coordinator(hass)
        result = await coordinator._async_update_data()

        fetched_at = result.get("fetched_at")
        assert fetched_at is not None
        parsed = datetime.fromisoformat(fetched_at)
        assert parsed.tzinfo is not None
        age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
        assert 0 <= age_seconds < 60


class TestTemperatureSensorHeartbeat:
    def _sensor(self, hass: HomeAssistant, key: str) -> ECCurrentSensor:
        coordinator = _make_coordinator(hass)
        coordinator.data = {
            "current": {"temp": -10.0},
            "fetched_at": "2026-07-04T18:00:00+00:00",
        }
        return ECCurrentSensor(coordinator, _description(key), "on-118", "Ottawa")

    def test_temperature_exposes_fetched_at(self, hass: HomeAssistant):
        sensor = self._sensor(hass, "ec_temperature")
        attributes = sensor.extra_state_attributes
        assert attributes == {"fetched_at": "2026-07-04T18:00:00+00:00"}

    def test_other_current_sensors_stay_attribute_free(self, hass: HomeAssistant):
        """Only one heartbeat carrier — stamping every sensor would force
        state writes across the board."""
        sensor = self._sensor(hass, "ec_humidity")
        assert sensor.extra_state_attributes is None

    def test_heartbeat_not_recorded(self, hass: HomeAssistant):
        """fetched_at changes every poll — keep it out of the recorder."""
        sensor = self._sensor(hass, "ec_temperature")
        assert "fetched_at" in sensor._unrecorded_attributes


class TestCardStaleness:
    def test_card_reads_heartbeat_with_fallback(self):
        """The card measures staleness from fetched_at (heartbeat), falling
        back to last_updated for servers running an older integration."""
        source = CARD_JS.read_text()
        start = source.find("_renderCurrent() {")
        section = source[start:source.find("_renderHourly() {", start)]
        assert "staleInfo(" in section

    def test_stale_decision_is_a_pure_helper(self):
        source = CARD_JS.read_text()
        assert "export function staleInfo(" in source
        start = source.find("export function staleInfo(")
        body = source[start:start + 700]
        assert "fetched_at" in body
        assert "last_updated" in body
