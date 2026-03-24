"""Sensor platform for the EC Weather integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL, PERCENTAGE, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_CODE, COORDINATOR_ALERTS, COORDINATOR_AQHI, COORDINATOR_WEATHER, COORDINATOR_WEONG, DOMAIN, GAUGE_TEMP_MAX, GAUGE_TEMP_MIN
from .coordinator import ECAlertCoordinator, ECAQHICoordinator, ECWeatherCoordinator
from .transforms import _build_unified_hourly, _filter_past_hours, _merge_weong_into_daily
from .weong import ECWEonGCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ECCurrentSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with coordinator data-path info."""

    data_key: str = ""
    # True → value is at coordinator.data[data_key] (top level)
    # False → value is at coordinator.data["current"][data_key]
    top_level: bool = False


@dataclass(frozen=True, kw_only=True)
class ECGaugeSensorDescription(SensorEntityDescription):
    """Description for a gauge sensor targeting iOS lock screen widgets."""

    current_key: str = ""   # key in coordinator.data["current"]
    high_key: str = ""      # key in coordinator.data["daily"][n]
    low_key: str = ""       # key in coordinator.data["daily"][n]


CURRENT_SENSOR_DESCRIPTIONS: tuple[ECCurrentSensorDescription, ...] = (
    ECCurrentSensorDescription(
        key="ec_temperature",
        name="EC Temperature",
        data_key="temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ECCurrentSensorDescription(
        key="ec_feels_like",
        name="EC Feels Like",
        data_key="feels_like",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ECCurrentSensorDescription(
        key="ec_humidity",
        name="EC Humidity",
        data_key="humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ECCurrentSensorDescription(
        key="ec_wind_speed",
        name="EC Wind Speed",
        data_key="wind_speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ECCurrentSensorDescription(
        key="ec_wind_gust",
        name="EC Wind Gust",
        data_key="wind_gust",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ECCurrentSensorDescription(
        key="ec_wind_direction",
        name="EC Wind Direction",
        data_key="wind_direction",
    ),
    ECCurrentSensorDescription(
        key="ec_condition",
        name="EC Condition",
        data_key="condition",
    ),
    ECCurrentSensorDescription(
        key="ec_icon_code",
        name="EC Icon Code",
        data_key="icon_code",
    ),
    ECCurrentSensorDescription(
        key="ec_sunrise",
        name="EC Sunrise",
        data_key="sunrise",
        top_level=True,
    ),
    ECCurrentSensorDescription(
        key="ec_sunset",
        name="EC Sunset",
        data_key="sunset",
        top_level=True,
    ),
)


GAUGE_SENSOR_DESCRIPTIONS: tuple[ECGaugeSensorDescription, ...] = (
    ECGaugeSensorDescription(
        key="ec_temp_gauge",
        name="EC Temperature Gauge",
        current_key="temp",
        high_key="temp_high",
        low_key="temp_low",
    ),
    ECGaugeSensorDescription(
        key="ec_feels_gauge",
        name="EC Feels Like Gauge",
        current_key="feels_like",
        high_key="feels_like_high",
        low_key="feels_like_low",
    ),
)


def _resolve_today_range(
    daily: list[dict], key_high: str, key_low: str
) -> tuple[float | None, float | None]:
    """Extract today's high and low from daily forecast data.

    When daily[0] is a night-only period (e.g. "Tonight"), temp_high is None.
    In that case, fall back to daily[1]'s high (next full day).
    """
    if not daily:
        return None, None
    high = daily[0].get(key_high)
    low = daily[0].get(key_low)
    if high is None and len(daily) > 1:
        high = daily[1].get(key_high)
    if low is None and len(daily) > 1:
        low = daily[1].get(key_low)
    return high, low


def _format_temp_label(temp: float | None) -> str | None:
    """Format a temperature as an integer, e.g. '-14'."""
    if temp is None:
        return None
    return str(int(round(temp)))


class ECGaugeSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Pre-computed gauge sensor for iOS lock screen widget.

    State: float 0.0–1.0 representing gauge arc fill position.
    Attributes: value, low, high (pre-formatted temperature strings).
    """

    entity_description: ECGaugeSensorDescription

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        description: ECGaugeSensorDescription,
        city_code: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{description.key}_{city_code}"

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        current = self.coordinator.data.get("current") or {}
        temp = current.get(self.entity_description.current_key)
        if temp is None:
            return None
        normalized = (temp - GAUGE_TEMP_MIN) / (GAUGE_TEMP_MAX - GAUGE_TEMP_MIN)
        return round(max(0.0, min(1.0, normalized)), 3)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        current = self.coordinator.data.get("current") or {}
        daily = self.coordinator.data.get("daily") or []
        desc = self.entity_description
        current_temp = current.get(desc.current_key)
        high, low = _resolve_today_range(daily, desc.high_key, desc.low_key)
        return {
            "value": _format_temp_label(current_temp),
            "low": _format_temp_label(low),
            "high": _format_temp_label(high),
        }


class ECCurrentSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Scalar sensor reading a single value from ECWeatherCoordinator."""

    entity_description: ECCurrentSensorDescription

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        description: ECCurrentSensorDescription,
        city_code: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{description.key}_{city_code}"

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        if self.entity_description.top_level:
            return self.coordinator.data.get(self.entity_description.data_key)
        current = self.coordinator.data.get("current") or {}
        return current.get(self.entity_description.data_key)


class ECForecastSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Sensor exposing a forecast array as an attribute.

    State: ISO timestamp of the last successful coordinator update.
    Attribute 'forecast': list of hourly or daily forecast dicts.
    """

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        unique_id: str,
        name: str,
        data_key: str,
        city_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{unique_id}_{city_code}"
        self._attr_name = name
        self._data_key = data_key

    @property
    def native_value(self) -> str | None:
        """Return the last update timestamp as the sensor state."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("updated")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {"forecast": []}
        return {"forecast": self.coordinator.data.get(self._data_key) or []}


class ECHourlyForecastSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Hourly forecast sensor merging EC hourly + WEonG data into a unified 48h list.

    Listens to both ECWeatherCoordinator (for EC hourly forecast, ~24h) and
    ECWEonGCoordinator (for WEonG per-timestep data, ~48h), and builds a unified
    hourly list with EC data preferred where available.
    """

    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_hourly_forecast_{city_code}"
        self._attr_name = "EC Hourly Forecast"
        self._weong_coordinator = weong_coordinator

    @property
    def available(self) -> bool:
        """Available when weather coordinator has data."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """Register listener for the WEonG coordinator too."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._weong_coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        )

    def _handle_coordinator_update(self) -> None:
        """Trigger a state update when WEonG data changes."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("updated")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {"forecast": []}

        ec_hourly = self.coordinator.data.get("hourly") or []
        weong_hourly = {}
        if self._weong_coordinator.data:
            weong_hourly = self._weong_coordinator.data.get("hourly") or {}

        if not weong_hourly:
            # No WEonG data — return EC hourly with null precip amounts
            result = []
            for item in ec_hourly:
                enriched = dict(item)
                enriched["rain_amt_mm"] = None
                enriched["snow_amt_cm"] = None
                result.append(enriched)
            return {"forecast": _filter_past_hours(result)}

        return {"forecast": _filter_past_hours(
            _build_unified_hourly(ec_hourly, weong_hourly)
        )}


class ECDailyForecastSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Daily forecast sensor that merges WEonG POP data into the forecast.

    Listens to both ECWeatherCoordinator (for the daily periods) and
    ECWEonGCoordinator (for precipitation probability/amounts), and merges
    them by matching (date, day/night) keys.
    """

    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_daily_forecast_{city_code}"
        self._attr_name = "EC Daily Forecast"
        self._weong_coordinator = weong_coordinator

    @property
    def available(self) -> bool:
        """Available when weather coordinator has data."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """Register listener for the WEonG coordinator too."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._weong_coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        )

    def _handle_coordinator_update(self) -> None:
        """Trigger a state update when WEonG data changes."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("updated")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {"forecast": []}

        daily = self.coordinator.data.get("daily") or []
        hourly = self.coordinator.data.get("hourly") or []
        weong_periods = {}
        if self._weong_coordinator.data:
            weong_periods = self._weong_coordinator.data.get("periods") or {}

        if not weong_periods:
            return {"forecast": daily}

        try:
            return {"forecast": _merge_weong_into_daily(daily, weong_periods, hourly)}
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC weather: failed to merge WEonG data into daily forecast")
            return {"forecast": daily}


class ECAQHISensor(CoordinatorEntity[ECAQHICoordinator], SensorEntity):
    """Sensor reporting the current Air Quality Health Index.

    State: integer AQHI value (1–10+), or None when unavailable.
    Attributes: risk_level, observation_time.
    """

    _attr_name = "EC Air Quality"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ECAQHICoordinator, city_code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_aqhi_{city_code}"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("aqhi")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        return {
            "risk_level": self.coordinator.data.get("risk_level"),
            "forecast_datetime": self.coordinator.data.get("forecast_datetime"),
        }


class ECWeatherSummarySensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Pre-formatted weather summary for the HA companion app widget.

    State: formatted string e.g. "-8° · Feels -11° · Mostly Cloudy"
    The "Feels X°" segment is omitted when feels-like equals actual temp.
    The "Next hour: Xcm" segment is omitted when no precip amount is available.
    """

    _attr_name = "EC Weather Summary"

    def __init__(self, coordinator: ECWeatherCoordinator, city_code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_weather_summary_{city_code}"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None

        current = self.coordinator.data.get("current") or {}
        hourly = self.coordinator.data.get("hourly") or []

        temp = current.get("temp")
        feels_like = current.get("feels_like")
        condition = current.get("condition")

        if temp is None:
            return None

        parts: list[str] = [f"{int(round(temp))}°"]

        # Include feels-like only when it meaningfully differs from actual temp
        if feels_like is not None and round(feels_like) != round(temp):
            parts.append(f"Feels {int(round(feels_like))}°")

        if condition:
            parts.append(str(condition).title())

        # Next-hour precip amount — omit when null or zero (EC hourly API rarely provides this)
        if hourly:
            next_hour = hourly[0]
            precip_amount = next_hour.get("precip_amount")
            precip_unit = next_hour.get("precip_unit")
            if precip_amount is not None and float(precip_amount) > 0 and precip_unit:
                parts.append(f"Next hour: {precip_amount}{precip_unit}")

        return " · ".join(parts)


class ECAlertCountSensor(CoordinatorEntity[ECAlertCoordinator], SensorEntity):
    """Sensor reporting the number of active weather alerts."""

    _attr_name = "EC Alert Count"

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alert_count_{city_code}"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("alert_count") or 0


class ECAlertsSensor(CoordinatorEntity[ECAlertCoordinator], SensorEntity):
    """Sensor exposing the full alerts list as an attribute.

    State: highest alert type present ("warning", "watch", "advisory", "statement")
           or None when no alerts are active.
    Attribute 'alerts': list of alert dicts (headline, type, expires, text).
    """

    _unrecorded_attributes = frozenset({MATCH_ALL})
    _attr_name = "EC Alerts"

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alerts_{city_code}"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("highest_type")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {"alerts": []}
        return {"alerts": self.coordinator.data.get("alerts") or []}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EC Weather sensor entities from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    weather_coordinator: ECWeatherCoordinator = entry_data[COORDINATOR_WEATHER]
    alert_coordinator: ECAlertCoordinator = entry_data[COORDINATOR_ALERTS]
    aqhi_coordinator: ECAQHICoordinator = entry_data[COORDINATOR_AQHI]
    weong_coordinator: ECWEonGCoordinator = entry_data[COORDINATOR_WEONG]
    city_code = entry.data[CONF_CITY_CODE]

    entities: list = [
        ECCurrentSensor(weather_coordinator, description, city_code)
        for description in CURRENT_SENSOR_DESCRIPTIONS
    ]
    entities.append(
        ECHourlyForecastSensor(weather_coordinator, weong_coordinator, city_code)
    )
    entities.append(
        ECDailyForecastSensor(weather_coordinator, weong_coordinator, city_code)
    )
    entities.append(ECWeatherSummarySensor(weather_coordinator, city_code))
    entities.extend(
        ECGaugeSensor(weather_coordinator, desc, city_code) for desc in GAUGE_SENSOR_DESCRIPTIONS
    )

    entities.append(ECAlertCountSensor(alert_coordinator, city_code))
    entities.append(ECAlertsSensor(alert_coordinator, city_code))
    entities.append(ECAQHISensor(aqhi_coordinator, city_code))

    async_add_entities(entities)
