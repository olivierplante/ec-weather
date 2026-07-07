"""Tests for yesterday's-precipitation sensors (issue #9, Part B).

Sensor-set selection and value mapping are pulled into pure helpers so the
null-vs-zero honesty rule is verifiable without a full hass:

- Split station → rain + snow + precipitation sensors.
- Combined station → precipitation sensor only.
- Unpublished/null source value → sensor state None (HA renders "unknown").
- Measured 0 → sensor state 0 (a real dry-day reading).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ec_weather.sensor import (
    ECYesterdayPrecipSensor,
    stale_precip_unique_ids,
    yesterday_precip_sensor_keys,
    yesterday_precip_value,
)


class TestSensorSetSelection:
    def test_split_station_gets_three_sensors(self):
        keys = yesterday_precip_sensor_keys("split")
        assert set(keys) == {
            "yesterday_rain",
            "yesterday_snow",
            "yesterday_precipitation",
        }

    def test_combined_station_gets_precip_only(self):
        keys = yesterday_precip_sensor_keys("combined")
        assert keys == ["yesterday_precipitation"]


class TestValueMapping:
    def test_null_source_is_none_not_zero(self):
        """Unpublished (None) must stay None, never coerced to 0."""
        data = {"published": False, "total_mm": None, "rain_mm": None, "snow_cm": None}
        assert yesterday_precip_value(data, "yesterday_precipitation") is None
        assert yesterday_precip_value(data, "yesterday_rain") is None
        assert yesterday_precip_value(data, "yesterday_snow") is None

    def test_measured_zero_is_zero(self):
        """A published dry day reads 0, not None."""
        data = {"published": True, "total_mm": 0, "rain_mm": 0, "snow_cm": 0}
        assert yesterday_precip_value(data, "yesterday_precipitation") == 0
        assert yesterday_precip_value(data, "yesterday_rain") == 0
        assert yesterday_precip_value(data, "yesterday_snow") == 0

    def test_wet_values_passthrough(self):
        data = {"published": True, "total_mm": 8.4, "rain_mm": 2.2, "snow_cm": 6.2}
        assert yesterday_precip_value(data, "yesterday_precipitation") == 8.4
        assert yesterday_precip_value(data, "yesterday_rain") == 2.2
        assert yesterday_precip_value(data, "yesterday_snow") == 6.2

    def test_unpublished_overrides_stale_values(self):
        """If not published, all sensors read None even if stale numbers linger."""
        data = {"published": False, "total_mm": 5.0, "rain_mm": 5.0, "snow_cm": 0}
        assert yesterday_precip_value(data, "yesterday_precipitation") is None

    def test_none_data_is_none(self):
        assert yesterday_precip_value(None, "yesterday_precipitation") is None


class TestStaleCleanup:
    """Switching split->combined leaves rain/snow orphaned; identify them so
    the platform can remove them from the entity registry on reload."""

    def test_combined_marks_rain_and_snow_stale(self):
        stale = stale_precip_unique_ids("combined", "qc-68")
        assert set(stale) == {"ec_yesterday_rain_qc-68", "ec_yesterday_snow_qc-68"}

    def test_split_marks_nothing_stale(self):
        assert stale_precip_unique_ids("split", "qc-68") == []

    def test_unconfigured_marks_all_three_stale(self):
        """No station (None) → every precip sensor is stale."""
        stale = stale_precip_unique_ids(None, "qc-68")
        assert set(stale) == {
            "ec_yesterday_rain_qc-68",
            "ec_yesterday_snow_qc-68",
            "ec_yesterday_precipitation_qc-68",
        }


class TestEntityId:
    """The card reads short entity_ids; sensors must pin them, not let HA
    prefix the device slug (which yields sensor.ec_weather_<city>_...)."""

    def test_entity_id_is_short_form(self):
        coord = MagicMock()
        coord.data = None
        sensor = ECYesterdayPrecipSensor(
            coord, "yesterday_precipitation", "qc-68", "Saint-Jérôme"
        )
        assert sensor.entity_id == "sensor.ec_yesterday_precipitation"

    def test_rain_and_snow_entity_ids(self):
        coord = MagicMock()
        coord.data = None
        rain = ECYesterdayPrecipSensor(coord, "yesterday_rain", "qc-68", "X")
        snow = ECYesterdayPrecipSensor(coord, "yesterday_snow", "qc-68", "X")
        assert rain.entity_id == "sensor.ec_yesterday_rain"
        assert snow.entity_id == "sensor.ec_yesterday_snow"
