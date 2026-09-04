"""Tests for the short entity_id constructor pins (issue #12).

The Lovelace card resolves its entities at runtime by role via the
``ec_weather/entities`` websocket command (the contract) — entity_ids no longer
matter for correctness. The constructor pins are now purely COSMETIC: on a
fresh install they still give the user pleasant short ids (sensor.ec_temperature)
for their own automations, instead of HA's device-prefixed default. These tests
guard that the pins remain in place; the retired unique_id-to-short-id migration
map and its tests were removed with the discovery work.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ec_weather.binary_sensor import ECAlertActiveSensor
from ec_weather.sensor import (
    CURRENT_SENSOR_DESCRIPTIONS,
    GAUGE_SENSOR_DESCRIPTIONS,
    ECAlertsSensor,
    ECAQHISensor,
    ECCurrentSensor,
    ECDailyForecastSensor,
    ECGaugeSensor,
    ECHourlyForecastSensor,
)

from .conftest import ENTITIES_DOCS_PATH

CITY_CODE = "on-118"
CITY_NAME = "Ottawa"


def _coord() -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = None
    return coordinator


# ---------------------------------------------------------------------------
# (a) Pinned entity_id on construction
# ---------------------------------------------------------------------------

class TestPinnedEntityIds:
    @pytest.mark.parametrize(
        "description", CURRENT_SENSOR_DESCRIPTIONS, ids=lambda d: d.key
    )
    def test_current_sensor_pins_short_id(self, description):
        sensor = ECCurrentSensor(_coord(), description, CITY_CODE, CITY_NAME)
        assert sensor.entity_id == f"sensor.{description.key}"

    def test_hourly_forecast_pins_short_id(self):
        sensor = ECHourlyForecastSensor(
            _coord(), _coord(), CITY_CODE, CITY_NAME, "en"
        )
        assert sensor.entity_id == "sensor.ec_hourly_forecast"

    def test_daily_forecast_pins_short_id(self):
        sensor = ECDailyForecastSensor(
            _coord(), _coord(), CITY_CODE, CITY_NAME, "en"
        )
        assert sensor.entity_id == "sensor.ec_daily_forecast"

    def test_aqhi_pins_short_id(self):
        sensor = ECAQHISensor(_coord(), CITY_CODE, CITY_NAME)
        assert sensor.entity_id == "sensor.ec_air_quality"

    def test_alerts_pins_short_id(self):
        sensor = ECAlertsSensor(_coord(), CITY_CODE, CITY_NAME)
        assert sensor.entity_id == "sensor.ec_alerts"

    def test_alert_active_pins_short_id(self):
        sensor = ECAlertActiveSensor(_coord(), CITY_CODE, CITY_NAME)
        assert sensor.entity_id == "binary_sensor.ec_alert_active"

    @pytest.mark.parametrize(
        ("key", "expected_entity_id"),
        [
            ("ec_temp_gauge", "sensor.ec_temperature_gauge"),
            ("ec_feels_gauge", "sensor.ec_feels_like_gauge"),
        ],
    )
    def test_gauge_sensor_pins_long_form_id(self, key, expected_entity_id):
        description = next(d for d in GAUGE_SENSOR_DESCRIPTIONS if d.key == key)
        sensor = ECGaugeSensor(_coord(), description, CITY_CODE, CITY_NAME)
        assert sensor.entity_id == expected_entity_id


# ---------------------------------------------------------------------------
# (b) Gauge docs match the pinned entity_ids (guards doc drift on issue #12)
# ---------------------------------------------------------------------------

class TestGaugeDocsMatchPins:
    def _docs_text(self) -> str:
        return ENTITIES_DOCS_PATH.read_text()

    @pytest.mark.parametrize("description", GAUGE_SENSOR_DESCRIPTIONS, ids=lambda d: d.key)
    def test_pinned_gauge_id_is_documented(self, description):
        sensor = ECGaugeSensor(_coord(), description, CITY_CODE, CITY_NAME)
        assert sensor.entity_id in self._docs_text()

    @pytest.mark.parametrize(
        "stale_entity_id", ["sensor.ec_temp_gauge", "sensor.ec_feels_gauge"]
    )
    def test_stale_gauge_id_is_not_documented(self, stale_entity_id):
        assert stale_entity_id not in self._docs_text()
