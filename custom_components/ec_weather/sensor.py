"""Sensor platform for the EC Weather integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

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
from .coordinator import ECAlertCoordinator, ECAQHICoordinator, ECWeatherCoordinator, ECWEonGCoordinator


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


def _derive_icon(weong: dict, hour: int) -> tuple[int | None, str | None]:
    """Derive an EC-style icon_code and condition text from WEonG data.

    Used for the hourly sensor (has raw precip types + sky_state) and
    the daily timestep enrichment (has only folded rain_mm/snow_cm + temp_c).

    Priority (by severity):
      1. freezing_precip_mm > 0 → freezing rain (14)
      2. ice_pellet_cm > 0 → ice pellets (27)
      3. snow + rain both > 0 → mixed (15)
      4. snow > 0 → snow (17)
      5. rain > 0 + temp < 0 → freezing rain (14) — temp-based fallback
      6. rain > 0 → rain (12)
      7. sky_state available → cloud cover + time of day
      8. None — no data to derive from
    """
    freezing = weong.get("freezing_precip_mm") or 0
    ice = weong.get("ice_pellet_cm") or 0
    # Support both key conventions: hourly sensor uses rain_amt_mm/snow_amt_cm,
    # daily timesteps use rain_mm/snow_cm
    rain = weong.get("rain_amt_mm") or weong.get("rain_mm") or 0
    snow = weong.get("snow_amt_cm") or weong.get("snow_cm") or 0
    temp = weong.get("temp_c")

    if freezing > 0:
        return 14, "Freezing rain"
    if ice > 0:
        return 27, "Ice pellets"
    if snow > 0 and rain > 0:
        return 15, "Rain and snow"
    if snow > 0:
        return 17, "Snow"
    if rain > 0 and temp is not None and temp < 0:
        return 14, "Freezing rain"
    if rain > 0:
        return 12, "Rain"

    # Dry — use SkyState if available
    sky = weong.get("sky_state")
    if sky is not None:
        is_night = hour < 6 or hour >= 18
        if sky <= 2:
            return (30, "Clear") if is_night else (0, "Sunny")
        if sky <= 4:
            return (31, "Mainly clear") if is_night else (1, "Mainly sunny")
        if sky <= 6:
            return (32, "Partly cloudy") if is_night else (2, "Partly cloudy")
        if sky <= 8:
            return (33, "Mostly cloudy") if is_night else (3, "Mostly cloudy")
        return 10, "Cloudy"

    return None, None


def _apply_icon_fallback(entry: dict, ts_iso: str) -> None:
    """Derive icon_code from WEonG data if not already set on the entry.

    Parses the hour from the ISO timestamp and uses _derive_icon to set
    icon_code and condition from sky_state/precip data.
    """
    if entry.get("icon_code") is not None:
        return
    try:
        hour = int(ts_iso[11:13])
    except (ValueError, IndexError):
        hour = 12
    icon_code, condition = _derive_icon(entry, hour)
    entry["icon_code"] = icon_code
    entry["condition"] = condition


def _build_unified_hourly(
    ec_hourly: list[dict], weong_hourly: dict
) -> list[dict]:
    """Build a unified hourly forecast list from EC hourly + WEonG data.

    EC hourly items (0–24h) are the primary source with full data (icon, condition,
    feels_like, wind). WEonG data enriches EC items with precip amounts and extends
    the forecast to ~48h with derived icons for hours beyond EC coverage.
    """
    # Index EC hourly items by timestamp — EC data always wins
    ec_lookup: dict[str, dict] = {}
    for item in ec_hourly:
        ts = item.get("datetime")
        if ts:
            ec_lookup[ts] = item

    # Collect all timestamps from both sources
    all_timestamps: set[str] = set(ec_lookup.keys())
    all_timestamps.update(weong_hourly.keys())

    result = []
    for ts in sorted(all_timestamps):
        ec = ec_lookup.get(ts)
        weong = weong_hourly.get(ts)

        if ec:
            # EC hourly item — enrich with WEonG precip amounts
            enriched = dict(ec)
            if weong:
                enriched["rain_amt_mm"] = weong.get("rain_amt_mm")
                enriched["snow_amt_cm"] = weong.get("snow_amt_cm")
                # Derive icon from WEonG if EC didn't provide one
                _apply_icon_fallback(enriched, ts)
            else:
                enriched["rain_amt_mm"] = None
                enriched["snow_amt_cm"] = None
            result.append(enriched)
        elif weong:
            # WEonG-only item (beyond EC 24h) — build with derived icon
            derived = dict(weong)
            _apply_icon_fallback(derived, ts)
            result.append({
                "datetime": ts,
                "temp": derived.get("temp_c"),
                "feels_like": None,
                "condition": derived.get("condition"),
                "icon_code": derived.get("icon_code"),
                "precip_prob": weong.get("pop"),
                "precip_amount": None,
                "precip_unit": None,
                "wind_speed": None,
                "wind_gust": None,
                "wind_direction": None,
                "rain_amt_mm": weong.get("rain_amt_mm"),
                "snow_amt_cm": weong.get("snow_amt_cm"),
            })

    return result


def _filter_past_hours(forecast: list[dict]) -> list[dict]:
    """Remove hourly items whose hour has already passed.

    Keeps the current hour (floor of now) and all future hours.
    """
    now = datetime.now(timezone.utc)
    # Truncate to the start of the current hour
    cutoff = now.replace(minute=0, second=0, microsecond=0)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [item for item in forecast if item.get("datetime", "") >= cutoff_str]


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
        """Available only when both weather and WEonG data are ready."""
        return (
            self.coordinator.last_update_success
            and self._weong_coordinator.data is not None
        )

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


def _merge_weong_into_daily(
    daily_periods: list[dict],
    weong_periods: dict,
    hourly_forecast: list[dict] | None = None,
) -> list[dict]:
    """Merge WEonG POP data and per-timestep breakdowns into daily forecast periods.

    The daily forecast contains unified day/night items (from _parse_daily):
    - Night-only item (e.g. "Tonight"): temp_high=None, temp_low set
    - Full day+night pair (e.g. "Sunday"): both temp_high and temp_low set
    - Day-only item (e.g. last "Friday"): temp_high set, temp_low=None

    The WEonG coordinator stores data keyed by (date_str, "day"|"night") tuples.
    Each daily item includes a ``date`` field (ISO string) set by _parse_daily,
    which is used to match WEonG periods directly — no date guessing needed.

    When hourly_forecast is provided, timesteps within the first 24h are enriched
    with EC hourly data (icon, condition, wind, feels-like) by matching UTC timestamps.
    """
    # Build lookup from EC hourly forecast by ISO timestamp
    hourly_lookup: dict[str, dict] = {}
    if hourly_forecast:
        for h in hourly_forecast:
            ts = h.get("datetime")
            if ts:
                hourly_lookup[ts] = h

    merged = []

    for period in daily_periods:
        enriched = dict(period)
        has_day = period.get("temp_high") is not None
        has_night = period.get("temp_low") is not None
        is_night_only = not has_day and has_night

        date_str = period.get("date")
        if not date_str:
            merged.append(enriched)
            continue

        # Match WEonG data by date embedded in each daily item
        day_data = weong_periods.get((date_str, "day")) if has_day else None
        night_data = weong_periods.get((date_str, "night")) if (has_night or is_night_only) else None

        def _extract(d, key):
            return d[key] if d and d.get(key) is not None else None

        # Day precip fields (None for night-only periods)
        enriched["precip_prob_day"] = _extract(day_data, "pop")
        enriched["snow_amt_cm_day"] = _extract(day_data, "snow_amt_cm")
        enriched["rain_amt_mm_day"] = _extract(day_data, "rain_amt_mm")

        # Night precip fields
        enriched["precip_prob_night"] = _extract(night_data, "pop")
        enriched["snow_amt_cm_night"] = _extract(night_data, "snow_amt_cm")
        enriched["rain_amt_mm_night"] = _extract(night_data, "rain_amt_mm")

        # Combined max (kept for backward compatibility)
        sub_periods = [s for s in [day_data, night_data] if s]
        pops = [s["pop"] for s in sub_periods if s.get("pop") is not None]
        enriched["precip_prob"] = max(pops) if pops else None

        # Per-timestep breakdowns for the timeline
        # Enrich WEonG timesteps with EC hourly data where available,
        # derive icons for timesteps without EC data
        def _enrich_timesteps(weong_data):
            if not weong_data:
                return []
            raw_ts = weong_data.get("timesteps") or []
            result = []
            for ts in raw_ts:
                entry = dict(ts)
                hourly = hourly_lookup.get(ts.get("time"))
                if hourly:
                    # Prefer EC hourly temp over WEonG temp when available
                    if hourly.get("temp") is not None:
                        entry["temp_c"] = round(hourly["temp"], 1)
                    entry["feels_like"] = hourly.get("feels_like")
                    # Only use EC icon if available; EC omits icon for current hour
                    if hourly.get("icon_code") is not None:
                        entry["icon_code"] = hourly["icon_code"]
                        entry["condition"] = hourly.get("condition")
                    entry["wind_speed"] = hourly.get("wind_speed")
                    entry["wind_direction"] = hourly.get("wind_direction")
                    entry["wind_gust"] = hourly.get("wind_gust")
                # Derive icon from WEonG sky_state/precip if still missing
                _apply_icon_fallback(entry, ts.get("time", ""))
                result.append(entry)
            return result

        enriched["timesteps_day"] = _enrich_timesteps(day_data) if not is_night_only else []
        enriched["timesteps_night"] = _enrich_timesteps(night_data)

        merged.append(enriched)

    return merged


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
        """Available only when both weather and WEonG data are ready."""
        return (
            self.coordinator.last_update_success
            and self._weong_coordinator.data is not None
        )

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
        except Exception:
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
