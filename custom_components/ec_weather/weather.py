"""Weather platform for the EC Weather integration.

Provides a WeatherEntity so the HA companion app can render a native
weather widget with icon, temperature, feels-like, and forecasts.
"""

from __future__ import annotations

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from datetime import datetime, timezone

from .const import CONF_CITY_CODE, CONF_CITY_NAME, CONF_LANGUAGE, DEFAULT_LANGUAGE, DOMAIN
from .coordinator import ECWeatherCoordinator, ECWEonGCoordinator, WEonGListenerMixin
from .icon_registry import icon_code_to_condition
from .models import ECWeatherData, build_device_info
from .transforms import filter_past_hours, merge_weong_into_daily


class ECWeather(WEonGListenerMixin, CoordinatorEntity[ECWeatherCoordinator], WeatherEntity):
    """Weather entity backed by the EC Weather custom integration."""

    _attr_has_entity_name = True
    _attr_name = "Weather"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY
        | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        weather_coordinator: ECWeatherCoordinator,
        weong_coordinator: ECWEonGCoordinator,
        city_code: str,
        city_name: str,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_weather_{city_code}"
        self._weong_coordinator = weong_coordinator
        self._attr_device_info = build_device_info(city_code, city_name)
        self._language = language

    # --- Current conditions ---

    @property
    def native_temperature(self) -> float | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("temp")

    @property
    def native_apparent_temperature(self) -> float | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("feels_like")

    @property
    def condition(self) -> str | None:
        if not self.coordinator.data:
            return None
        code = (self.coordinator.data.get("current") or {}).get("icon_code")
        return icon_code_to_condition(code)

    @property
    def humidity(self) -> float | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("humidity")

    @property
    def native_wind_speed(self) -> float | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("wind_speed")

    @property
    def native_wind_gust_speed(self) -> float | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("wind_gust")

    @property
    def wind_bearing(self) -> str | None:
        if not self.coordinator.data:
            return None
        return (self.coordinator.data.get("current") or {}).get("wind_direction")

    # --- Forecasts ---

    async def async_forecast_daily(self) -> list[Forecast]:
        if not self.coordinator.data:
            return []

        daily = self.coordinator.data.get("daily") or []

        # Merge WEonG POP data if available
        weong_periods = {}
        if self._weong_coordinator.data:
            weong_periods = self._weong_coordinator.data.get("periods") or {}
        if weong_periods:
            hourly = self.coordinator.data.get("hourly") or []
            daily = merge_weong_into_daily(
                daily, weong_periods, hourly, lang=self._language
            )

        forecasts: list[Forecast] = []
        for item in daily:
            forecast: Forecast = {
                "datetime": item.get("period", ""),
                "condition": icon_code_to_condition(item.get("icon_code")),
                "temperature": item.get("temp_high"),
                "templow": item.get("temp_low"),
                "precipitation_probability": item.get("precip_prob"),  # from merge_weong_into_daily
                "wind_speed": None,
                "wind_bearing": None,
            }
            forecasts.append(forecast)
        return forecasts

    async def async_forecast_hourly(self) -> list[Forecast]:
        if not self.coordinator.data:
            return []

        hourly = filter_past_hours(self.coordinator.data.get("hourly") or [])

        forecasts: list[Forecast] = []
        for item in hourly:
            forecast: Forecast = {
                "datetime": item.get("time", ""),
                "condition": icon_code_to_condition(item.get("icon_code")),
                "temperature": item.get("temp"),
                "precipitation_probability": item.get("precipitation_probability"),
                "wind_speed": item.get("wind_speed"),
                "wind_bearing": item.get("wind_direction"),
            }
            forecasts.append(forecast)
        return forecasts


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EC Weather weather entity from a config entry."""
    data: ECWeatherData = hass.data[DOMAIN][entry.entry_id]
    city_code = entry.data[CONF_CITY_CODE]
    city_name = entry.data.get(CONF_CITY_NAME, city_code)
    language = entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    async_add_entities([ECWeather(data.weather, data.weong, city_code, city_name, language)])
