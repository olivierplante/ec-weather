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

from .const import CONF_CITY_CODE, COORDINATOR_WEATHER, COORDINATOR_WEONG, DOMAIN
from .coordinator import ECWeatherCoordinator
from .transforms import _merge_weong_into_daily
from .weong import ECWEonGCoordinator

# ---------------------------------------------------------------------------
# EC icon code → HA condition string mapping
#
# HA defines 15 standardized conditions. EC uses numeric icon codes 0-48.
# We map from the icon code (language-independent) rather than condition text.
# ---------------------------------------------------------------------------

_ICON_TO_CONDITION: dict[int, str] = {
    0: "sunny",
    1: "partlycloudy",
    2: "partlycloudy",
    3: "cloudy",
    4: "cloudy",
    5: "partlycloudy",
    6: "rainy",
    7: "snowy-rainy",
    8: "snowy",
    9: "lightning-rainy",
    10: "cloudy",
    11: "rainy",
    12: "rainy",
    13: "pouring",
    14: "hail",
    15: "snowy-rainy",
    16: "snowy",
    17: "snowy",
    18: "snowy",
    19: "lightning-rainy",
    20: "windy",
    21: "fog",
    22: "partlycloudy",
    23: "fog",
    24: "fog",
    25: "windy",
    26: "hail",
    27: "hail",
    28: "hail",
    29: "cloudy",
    30: "clear-night",
    31: "clear-night",
    32: "partlycloudy",
    33: "cloudy",
    34: "cloudy",
    35: "clear-night",
    36: "rainy",
    37: "snowy-rainy",
    38: "snowy",
    39: "lightning-rainy",
    40: "snowy",
    41: "exceptional",
    42: "exceptional",
    43: "windy",
    44: "fog",
    45: "windy",
    46: "lightning",
    47: "lightning",
    48: "exceptional",
}


def _icon_code_to_condition(code: int | None) -> str | None:
    """Map an EC icon code to an HA weather condition string."""
    if code is None:
        return None
    return _ICON_TO_CONDITION.get(code, "cloudy")


class ECWeather(CoordinatorEntity[ECWeatherCoordinator], WeatherEntity):
    """Weather entity backed by the EC Weather custom integration."""

    _attr_name = "EC Weather"
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
    ) -> None:
        super().__init__(weather_coordinator)
        self._attr_unique_id = f"ec_weather_{city_code}"
        self._weong_coordinator = weong_coordinator

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
        return _icon_code_to_condition(code)

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
            daily = _merge_weong_into_daily(daily, weong_periods)

        forecasts: list[Forecast] = []
        for item in daily:
            forecast: Forecast = {
                "datetime": item.get("period", ""),
                "condition": _icon_code_to_condition(item.get("icon_code")),
                "temperature": item.get("temp_high"),
                "templow": item.get("temp_low"),
                "precipitation_probability": item.get("precip_prob"),
                "wind_speed": None,
                "wind_bearing": None,
            }
            forecasts.append(forecast)
        return forecasts

    async def async_forecast_hourly(self) -> list[Forecast]:
        if not self.coordinator.data:
            return []

        hourly = self.coordinator.data.get("hourly") or []

        # Filter out past hours — keep current hour and future
        now = datetime.now(timezone.utc)
        cutoff = now.replace(minute=0, second=0, microsecond=0)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        forecasts: list[Forecast] = []
        for item in hourly:
            if item.get("datetime", "") < cutoff_str:
                continue
            forecast: Forecast = {
                "datetime": item.get("datetime", ""),
                "condition": _icon_code_to_condition(item.get("icon_code")),
                "temperature": item.get("temp"),
                "precipitation_probability": item.get("precip_prob"),
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
    entry_data = hass.data[DOMAIN][entry.entry_id]
    weather_coordinator: ECWeatherCoordinator = entry_data[COORDINATOR_WEATHER]
    weong_coordinator: ECWEonGCoordinator = entry_data[COORDINATOR_WEONG]
    city_code = entry.data[CONF_CITY_CODE]

    async_add_entities([ECWeather(weather_coordinator, weong_coordinator, city_code)])
