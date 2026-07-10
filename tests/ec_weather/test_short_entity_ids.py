"""Tests for short entity_id pinning + registry migration (issue #12).

The Lovelace card reads hardcoded short entity_ids (e.g. sensor.ec_temperature).
Since ``_attr_has_entity_name`` + device registration were added, HA prefixes
the device slug on fresh installs (sensor.ec_weather_<city>_ec_temperature),
which the card can't find. Every entity the card reads must:

- pin ``self.entity_id`` to the short form on construction, and
- be covered by the registry migration so entities from earlier builds get
  renamed away from the device-prefixed id.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ec_weather.binary_sensor import ECAlertActiveSensor
from ec_weather.models import migrate_short_entity_ids
from ec_weather.sensor import (
    CURRENT_SENSOR_DESCRIPTIONS,
    ECAlertsSensor,
    ECAQHISensor,
    ECCurrentSensor,
    ECDailyForecastSensor,
    ECHourlyForecastSensor,
    _short_entity_id_map,
)

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


# ---------------------------------------------------------------------------
# (b) Migration map completeness
# ---------------------------------------------------------------------------

class TestShortEntityIdMap:
    def test_map_covers_all_card_read_entities(self):
        mapping = _short_entity_id_map(CITY_CODE)

        expected = {}
        for description in CURRENT_SENSOR_DESCRIPTIONS:
            expected[f"{description.key}_{CITY_CODE}"] = f"sensor.{description.key}"
        expected[f"ec_hourly_forecast_{CITY_CODE}"] = "sensor.ec_hourly_forecast"
        expected[f"ec_daily_forecast_{CITY_CODE}"] = "sensor.ec_daily_forecast"
        expected[f"ec_aqhi_{CITY_CODE}"] = "sensor.ec_air_quality"
        expected[f"ec_alerts_{CITY_CODE}"] = "sensor.ec_alerts"
        expected[f"ec_precip_probability_today_{CITY_CODE}"] = (
            "sensor.ec_precip_probability_today"
        )
        expected[f"ec_yesterday_rain_{CITY_CODE}"] = "sensor.ec_yesterday_rain"
        expected[f"ec_yesterday_snow_{CITY_CODE}"] = "sensor.ec_yesterday_snow"
        expected[f"ec_yesterday_precipitation_{CITY_CODE}"] = (
            "sensor.ec_yesterday_precipitation"
        )

        assert mapping == expected

    def test_map_has_ten_current_sensor_slugs(self):
        mapping = _short_entity_id_map(CITY_CODE)
        current_slugs = {
            f"{description.key}_{CITY_CODE}"
            for description in CURRENT_SENSOR_DESCRIPTIONS
        }
        assert current_slugs <= set(mapping)
        assert len(current_slugs) == 10


# ---------------------------------------------------------------------------
# (c) Migration behaviour of the shared helper
# ---------------------------------------------------------------------------

class TestMigrateShortEntityIds:
    def test_prefixed_entity_is_renamed(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = (
            "sensor.ec_weather_ottawa_ec_temperature"
        )
        # Desired id is free.
        registry.async_get.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_called_once_with(
            "sensor.ec_weather_ottawa_ec_temperature",
            new_entity_id="sensor.ec_temperature",
        )

    def test_no_rename_when_target_id_taken(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = (
            "sensor.ec_weather_ottawa_ec_temperature"
        )
        # Desired id already used by another entity.
        registry.async_get.return_value = MagicMock()

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_not_called()

    def test_no_rename_when_already_short(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = "sensor.ec_temperature"

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_not_called()

    def test_no_rename_when_unique_id_absent(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_not_called()

    def test_user_custom_rename_is_preserved(self):
        """A user-chosen entity_id must never be renamed — only ids matching
        the auto-generated device-prefixed form are migrated."""
        registry = MagicMock()
        registry.async_get_entity_id.return_value = "sensor.outdoor_temp"
        registry.async_get.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_not_called()

    def test_collision_suffixed_prefixed_id_is_renamed(self):
        """HA collision suffixes (_2) keep the device prefix — still migrated."""
        registry = MagicMock()
        registry.async_get_entity_id.return_value = (
            "sensor.ec_weather_ottawa_ec_temperature_2"
        )
        registry.async_get.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "sensor",
                {f"ec_temperature_{CITY_CODE}": "sensor.ec_temperature"},
            )

        registry.async_update_entity.assert_called_once_with(
            "sensor.ec_weather_ottawa_ec_temperature_2",
            new_entity_id="sensor.ec_temperature",
        )

    def test_user_custom_rename_preserved_for_binary_sensor(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = "binary_sensor.storm_warning"
        registry.async_get.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "binary_sensor",
                {f"ec_alert_active_{CITY_CODE}": "binary_sensor.ec_alert_active"},
            )

        registry.async_update_entity.assert_not_called()

    def test_works_for_binary_sensor_domain(self):
        registry = MagicMock()
        registry.async_get_entity_id.return_value = (
            "binary_sensor.ec_weather_ottawa_ec_alert_active"
        )
        registry.async_get.return_value = None

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            migrate_short_entity_ids(
                MagicMock(),
                "binary_sensor",
                {
                    f"ec_alert_active_{CITY_CODE}": (
                        "binary_sensor.ec_alert_active"
                    )
                },
            )

        registry.async_get_entity_id.assert_called_once_with(
            "binary_sensor", "ec_weather", f"ec_alert_active_{CITY_CODE}"
        )
        registry.async_update_entity.assert_called_once_with(
            "binary_sensor.ec_weather_ottawa_ec_alert_active",
            new_entity_id="binary_sensor.ec_alert_active",
        )
