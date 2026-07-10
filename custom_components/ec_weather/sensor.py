"""Sensor platform for the EC Weather integration."""

from __future__ import annotations

import logging
import math
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
from homeassistant.const import (
    MATCH_ALL,
    PERCENTAGE,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_CODE, CONF_CITY_NAME, CONF_LANGUAGE, DOMAIN, GAUGE_TEMP_MAX, GAUGE_TEMP_MIN
from .coordinator import (
    ECAlertCoordinator,
    ECAQHICoordinator,
    ECClimateCoordinator,
    ECWeatherCoordinator,
    ECWEonGCoordinator,
    WEonGListenerMixin,
)
from .models import ECWeatherData, build_device_info, migrate_short_entity_ids
from .transforms import (
    build_unified_hourly,
    extract_today_pop,
    filter_past_hours,
    merge_weong_into_daily,
)

from homeassistant.util import dt as dt_util

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
        entity_category=EntityCategory.DIAGNOSTIC,
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
    """Format a temperature as an integer, e.g. '-14'.

    Rounds half UP like the card's JS Math.round (24.5 → 25, -24.5 → -24) —
    Python's built-in round() is half-to-even and made the iOS widget disagree
    with the dashboard by one degree on every .5 reading.
    """
    if temp is None:
        return None
    return str(math.floor(temp + 0.5))


class ECGaugeSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Pre-computed gauge sensor for iOS lock screen widget.

    State: float 0.0–1.0 representing gauge arc fill position.
    Attributes: value, low, high (pre-formatted temperature strings).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: ECGaugeSensorDescription

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        description: ECGaugeSensorDescription,
        city_code: str,
        city_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{description.key}_{city_code}"
        self._attr_device_info = build_device_info(city_code, city_name)

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
        description = self.entity_description
        current_temp = current.get(description.current_key)
        high, low = _resolve_today_range(daily, description.high_key, description.low_key)
        return {
            "value": _format_temp_label(current_temp),
            "low": _format_temp_label(low),
            "high": _format_temp_label(high),
        }


class ECCurrentSensor(CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Scalar sensor reading a single value from ECWeatherCoordinator."""

    _attr_has_entity_name = True
    entity_description: ECCurrentSensorDescription
    # fetched_at changes on every successful poll — keep it out of the recorder.
    _unrecorded_attributes = frozenset({"fetched_at"})

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        description: ECCurrentSensorDescription,
        city_code: str,
        city_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{description.key}_{city_code}"
        # Pin the entity_id to the short form the card reads. Without this,
        # has_entity_name prefixes the device slug, producing
        # sensor.ec_weather_<city>_... which the card can't find.
        self.entity_id = f"sensor.{description.key}"
        self._attr_device_info = build_device_info(city_code, city_name)

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        if self.entity_description.top_level:
            return self.coordinator.data.get(self.entity_description.data_key)
        current = self.coordinator.data.get("current") or {}
        return current.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict | None:
        # Only the temperature sensor carries the success heartbeat — the
        # card reads it to tell "EC values unchanged for hours" (fine) from
        # "fetching has been failing for hours" (stale banner). Stamping
        # every current sensor would force state writes across the board.
        if self.entity_description.key != "ec_temperature":
            return None
        if not self.coordinator.data:
            return None
        fetched_at = self.coordinator.data.get("fetched_at")
        return {"fetched_at": fetched_at} if fetched_at else None


class ECHourlyForecastSensor(WEonGListenerMixin, CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Hourly forecast sensor merging EC hourly + WEonG data into a unified 48h list.

    Listens to both ECWeatherCoordinator (for EC hourly forecast, ~24h) and
    ECWEonGCoordinator (for WEonG per-timestep data, ~48h), and builds a unified
    hourly list with EC data preferred where available.
    """

    _attr_has_entity_name = True
    _attr_name = "Hourly Forecast"
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
        city_name: str,
        language: str = "en",
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_hourly_forecast_{city_code}"
        # Pin the entity_id to the short form the card reads (avoids the
        # device-prefixed default from has_entity_name).
        self.entity_id = "sensor.ec_hourly_forecast"
        self._weong_coordinator = weong_coordinator
        self._attr_device_info = build_device_info(city_code, city_name)
        self._language = language

    @property
    def available(self) -> bool:
        """Available when weather coordinator has data."""
        return self.coordinator.last_update_success

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
                enriched["rain_mm"] = None
                enriched["snow_cm"] = None
                result.append(enriched)
            return {"forecast": filter_past_hours(result)}

        unified = filter_past_hours(
            build_unified_hourly(ec_hourly, weong_hourly, lang=self._language)
        )

        return {"forecast": unified}


class ECDailyForecastSensor(WEonGListenerMixin, CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Daily forecast sensor that merges WEonG POP data into the forecast.

    Listens to both ECWeatherCoordinator (for the daily periods) and
    ECWEonGCoordinator (for precipitation probability/amounts), and merges
    them by matching (date, day/night) keys.
    """

    _attr_has_entity_name = True
    _attr_name = "Daily Forecast"
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
        city_name: str,
        language: str = "en",
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_daily_forecast_{city_code}"
        # Pin the entity_id to the short form the card reads (avoids the
        # device-prefixed default from has_entity_name).
        self.entity_id = "sensor.ec_daily_forecast"
        self._weong_coordinator = weong_coordinator
        self._attr_device_info = build_device_info(city_code, city_name)
        self._language = language

    @property
    def available(self) -> bool:
        """Available when weather coordinator has data."""
        return self.coordinator.last_update_success

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
        ec_updated = self.coordinator.data.get("updated")
        weong_periods = {}
        weong_updated = None
        days_fetched = None
        precip_windows = None
        outlook = None
        outlook_backfill = None
        if self._weong_coordinator.data:
            weong_periods = self._weong_coordinator.data.get("periods") or {}
            weong_updated = self._weong_coordinator.data.get("updated")
            days_fetched = self._weong_coordinator.data.get("days_fetched")
            precip_windows = self._weong_coordinator.data.get("precip_windows")
            outlook = self._weong_coordinator.data.get("outlook")
            outlook_backfill = self._weong_coordinator.data.get("outlook_backfill")

        try:
            merged = merge_weong_into_daily(
                daily, weong_periods, hourly, lang=self._language,
                ec_updated=ec_updated, weong_updated=weong_updated,
                days_fetched=days_fetched, precip_windows=precip_windows,
                outlook=outlook, outlook_backfill=outlook_backfill,
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC weather: failed to merge WEonG data into daily forecast")
            return {"forecast": daily}

        # Filter past hours from today's timesteps
        now_local = dt_util.now()
        today_str = now_local.date().isoformat()
        for period in merged:
            if period.get("date") == today_str:
                period["timesteps_day"] = filter_past_hours(
                    period.get("timesteps_day") or []
                )
                period["timesteps_night"] = filter_past_hours(
                    period.get("timesteps_night") or []
                )

        # Drop leading night-only period ("Tonight") between 6 AM and 6 PM.
        # EC keeps it in the forecast until the next morning update, but
        # it's stale once the night has passed. After 6 PM, EC issues a
        # fresh "Tonight" for the upcoming night, so keep it.
        if merged and merged[0].get("temp_high") is None and 6 <= now_local.hour < 18:
            merged = merged[1:]

        return {"forecast": merged}


class ECTodayPopSensor(WEonGListenerMixin, CoordinatorEntity[ECWeatherCoordinator], SensorEntity):
    """Today's probability of precipitation (combined day/night max).

    State: integer percent (0-100), or None when WEonG data is unavailable.
    Reuses the same EC+WEonG merge as the daily forecast so the value matches
    what the daily column shows for today.
    """

    _attr_has_entity_name = True
    _attr_name = "Precipitation Probability Today"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
        city_name: str,
        language: str = "en",
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_precip_probability_today_{city_code}"
        # Pin the entity_id to the short form the card reads. Without this,
        # has_entity_name prefixes the device slug, producing
        # sensor.ec_weather_<city>_... which the card can't find.
        self.entity_id = "sensor.ec_precip_probability_today"
        self._weong_coordinator = weong_coordinator
        self._attr_device_info = build_device_info(city_code, city_name)
        self._language = language

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None

        daily = self.coordinator.data.get("daily") or []
        hourly = self.coordinator.data.get("hourly") or []
        ec_updated = self.coordinator.data.get("updated")
        weong_periods = {}
        weong_updated = None
        if self._weong_coordinator.data:
            weong_periods = self._weong_coordinator.data.get("periods") or {}
            weong_updated = self._weong_coordinator.data.get("updated")

        try:
            merged = merge_weong_into_daily(
                daily, weong_periods, hourly, lang=self._language,
                ec_updated=ec_updated, weong_updated=weong_updated,
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("EC weather: failed to merge WEonG data for today's POP")
            return None

        today_str = dt_util.now().date().isoformat()
        return extract_today_pop(merged, today_str)


class ECAQHISensor(CoordinatorEntity[ECAQHICoordinator], SensorEntity):
    """Sensor reporting the current Air Quality Health Index.

    State: integer AQHI value (1–10+), or None when unavailable.
    Attributes: risk_level, observation_time.
    """

    _attr_has_entity_name = True
    _attr_name = "Air Quality"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ECAQHICoordinator, city_code: str, city_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_aqhi_{city_code}"
        # Pin the entity_id to the short form the card reads (avoids the
        # device-prefixed default from has_entity_name).
        self.entity_id = "sensor.ec_air_quality"
        self._attr_device_info = build_device_info(city_code, city_name)

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
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Weather Summary"

    def __init__(
        self,
        coordinator: ECWeatherCoordinator,
        city_code: str,
        city_name: str,
        language: str = "en",
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_weather_summary_{city_code}"
        self._attr_device_info = build_device_info(city_code, city_name)
        self._language = language

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None

        current = self.coordinator.data.get("current") or {}

        temp = current.get("temp")
        feels_like = current.get("feels_like")
        condition = current.get("condition")

        if temp is None:
            return None

        parts: list[str] = [f"{int(round(temp))}°"]

        # Include feels-like only when it meaningfully differs from actual temp
        if feels_like is not None and round(feels_like) != round(temp):
            feels_label = "Ressenti" if self._language == "fr" else "Feels"
            parts.append(f"{feels_label} {int(round(feels_like))}°")

        if condition:
            parts.append(str(condition).title())

        return " · ".join(parts)


class ECAlertCountSensor(CoordinatorEntity[ECAlertCoordinator], SensorEntity):
    """Sensor reporting the number of active weather alerts."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Alert Count"

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str, city_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alert_count_{city_code}"
        self._attr_device_info = build_device_info(city_code, city_name)

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

    _attr_has_entity_name = True
    _attr_name = "Alerts"
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator: ECAlertCoordinator, city_code: str, city_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"ec_alerts_{city_code}"
        # Pin the entity_id to the short form the card reads (avoids the
        # device-prefixed default from has_entity_name).
        self.entity_id = "sensor.ec_alerts"
        self._attr_device_info = build_device_info(city_code, city_name)

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


# ---------------------------------------------------------------------------
# Yesterday's precipitation sensors (issue #9)
# ---------------------------------------------------------------------------

# Maps each sensor key to the coordinator-data field it reads.
_YESTERDAY_PRECIP_FIELDS = {
    "yesterday_rain": "rain_mm",
    "yesterday_snow": "snow_cm",
    "yesterday_precipitation": "total_mm",
}


def yesterday_precip_sensor_keys(station_type: str) -> list[str]:
    """Return the sensor keys to create for a given station type.

    Split stations expose rain + snow + total; combined stations expose only
    the total (they never report a rain/snow breakdown).
    """
    if station_type == "split":
        return ["yesterday_rain", "yesterday_snow", "yesterday_precipitation"]
    return ["yesterday_precipitation"]


def stale_precip_unique_ids(station_type: str | None, city_code: str) -> list[str]:
    """Return unique_ids of precip sensors that should NOT exist for this config.

    Used to clean up orphaned entities when the user switches station type
    (split -> combined drops rain/snow) or opts out (drops all three). HA does
    not auto-remove entities a platform stops creating, so we remove them
    explicitly from the registry on reload.
    """
    keep = set(yesterday_precip_sensor_keys(station_type)) if station_type else set()
    all_keys = {"yesterday_rain", "yesterday_snow", "yesterday_precipitation"}
    return [f"ec_{key}_{city_code}" for key in sorted(all_keys - keep)]


def yesterday_precip_value(data: dict | None, key: str):
    """Return the sensor value for a key, honouring null-vs-zero.

    When the day is not yet published, every sensor reads None (HA shows
    "unknown") — never 0. A measured 0 (published dry day) reads 0.
    """
    if not data or not data.get("published"):
        return None
    return data.get(_YESTERDAY_PRECIP_FIELDS[key])


class ECYesterdayPrecipSensor(CoordinatorEntity[ECClimateCoordinator], SensorEntity):
    """One of yesterday's precipitation readings (rain, snow, or total).

    State: the measured amount, 0 on a published dry day, or None (unknown)
    until yesterday's observation is published. Diagnostic attributes carry
    the reporting station's name, distance, and data type.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.PRECIPITATION

    _KEY_NAMES = {
        "yesterday_rain": "Yesterday's Rain",
        "yesterday_snow": "Yesterday's Snow",
        "yesterday_precipitation": "Yesterday's Precipitation",
    }
    _KEY_UNITS = {
        "yesterday_rain": UnitOfPrecipitationDepth.MILLIMETERS,
        "yesterday_snow": UnitOfPrecipitationDepth.CENTIMETERS,
        "yesterday_precipitation": UnitOfPrecipitationDepth.MILLIMETERS,
    }

    def __init__(
        self,
        coordinator: ECClimateCoordinator,
        key: str,
        city_code: str,
        city_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = self._KEY_NAMES[key]
        self._attr_native_unit_of_measurement = self._KEY_UNITS[key]
        self._attr_unique_id = f"ec_{key}_{city_code}"
        # Pin the entity_id to the short form the card reads (e.g.
        # sensor.ec_yesterday_precipitation), not the device-prefixed default.
        self.entity_id = f"sensor.ec_{key}"
        self._attr_device_info = build_device_info(city_code, city_name)

    @property
    def native_value(self):
        return yesterday_precip_value(self.coordinator.data, self._key)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "station_name": data.get("station_name"),
            "distance_km": data.get("distance_km"),
            "data_type": data.get("station_type"),
            "published": data.get("published"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EC Weather sensor entities from a config entry."""
    data: ECWeatherData = hass.data[DOMAIN][entry.entry_id]
    city_code = entry.data[CONF_CITY_CODE]
    city_name = entry.data.get(CONF_CITY_NAME, city_code)
    language = entry.data.get(CONF_LANGUAGE, "en")

    entities: list = [
        ECCurrentSensor(data.weather, description, city_code, city_name)
        for description in CURRENT_SENSOR_DESCRIPTIONS
    ]
    entities.append(
        ECHourlyForecastSensor(data.weather, data.weong, city_code, city_name, language)
    )
    entities.append(
        ECDailyForecastSensor(data.weather, data.weong, city_code, city_name, language)
    )
    entities.append(ECWeatherSummarySensor(data.weather, city_code, city_name, language))
    entities.append(
        ECTodayPopSensor(data.weather, data.weong, city_code, city_name, language)
    )
    entities.extend(
        ECGaugeSensor(data.weather, description, city_code, city_name)
        for description in GAUGE_SENSOR_DESCRIPTIONS
    )

    entities.append(ECAlertCountSensor(data.alerts, city_code, city_name))
    entities.append(ECAlertsSensor(data.alerts, city_code, city_name))
    entities.append(ECAQHISensor(data.aqhi, city_code, city_name))

    # Yesterday's precipitation — only when a station is configured.
    station_type = (
        data.climate.station_type
        if data.climate is not None and data.climate.station_id
        else None
    )
    if station_type:
        for key in yesterday_precip_sensor_keys(station_type):
            entities.append(
                ECYesterdayPrecipSensor(data.climate, key, city_code, city_name)
            )

    # Migrate any device-prefixed entity_ids from earlier builds to the short
    # ids the card reads, then remove sensors orphaned by a station-type change
    # or opt-out (HA doesn't auto-remove those).
    migrate_short_entity_ids(hass, "sensor", _short_entity_id_map(city_code))
    _remove_stale_precip_entities(hass, station_type, city_code)

    async_add_entities(entities)


def _remove_stale_precip_entities(
    hass: HomeAssistant, station_type: str | None, city_code: str
) -> None:
    """Delete precip entities from the registry that no longer apply."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for unique_id in stale_precip_unique_ids(station_type, city_code):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)
            _LOGGER.debug("Removed stale precip entity %s", entity_id)


# unique_id slug -> desired short entity_id, for every sensor the card reads by
# a fixed id. Earlier builds registered these with a device-prefixed entity_id
# (sensor.ec_weather_<city>_...), which the card can't find; migrate them.
def _short_entity_id_map(city_code: str) -> dict[str, str]:
    slugs = [description.key for description in CURRENT_SENSOR_DESCRIPTIONS]
    keys = {slug: f"sensor.{slug}" for slug in slugs}
    keys.update(
        {
            "ec_hourly_forecast": "sensor.ec_hourly_forecast",
            "ec_daily_forecast": "sensor.ec_daily_forecast",
            "ec_aqhi": "sensor.ec_air_quality",
            "ec_alerts": "sensor.ec_alerts",
            "ec_precip_probability_today": "sensor.ec_precip_probability_today",
            "ec_yesterday_rain": "sensor.ec_yesterday_rain",
            "ec_yesterday_snow": "sensor.ec_yesterday_snow",
            "ec_yesterday_precipitation": "sensor.ec_yesterday_precipitation",
        }
    )
    return {f"{slug}_{city_code}": eid for slug, eid in keys.items()}
