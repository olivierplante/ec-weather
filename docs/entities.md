# Entity reference

[← Back to README](../README.md)

All entities are grouped under a device named **"EC Weather — {City Name}"**.

## Current conditions

| Entity | State |
|---|---|
| `sensor.ec_temperature` | °C |
| `sensor.ec_feels_like` | °C (wind chill or humidex) |
| `sensor.ec_humidity` | % |
| `sensor.ec_wind_speed` | km/h |
| `sensor.ec_wind_gust` | km/h (null when absent) |
| `sensor.ec_wind_direction` | Cardinal (e.g. "NW") |
| `sensor.ec_condition` | Text (e.g. "Mostly Cloudy") |
| `sensor.ec_icon_code` | Integer 0 to 48, diagnostic |
| `sensor.ec_sunrise` | "HH:MM" local |
| `sensor.ec_sunset` | "HH:MM" local |

## Forecasts

| Entity | State | Attributes |
|---|---|---|
| `sensor.ec_hourly_forecast` | Last update timestamp | `forecast`: 48-hour list with temp, icon, POP, rain/snow |
| `sensor.ec_daily_forecast` | Last update timestamp | `forecast`: 7-day list with day/night split, timesteps |
| `sensor.ec_weather_summary` | e.g. "-8° · Feels -11° · Mostly Cloudy" | Diagnostic |

## Alerts

| Entity | State |
|---|---|
| `binary_sensor.ec_alert_active` | on/off |
| `sensor.ec_alert_count` | Integer, diagnostic |
| `sensor.ec_alerts` | Highest alert type; `alerts` attribute is the full list |

## Air quality

| Entity | State | Attributes |
|---|---|---|
| `sensor.ec_air_quality` | Float (e.g. 3.0) | `risk_level`, `forecast_datetime` |

## iOS lock screen gauge

Pre-computed for the HA Companion App's iOS lock screen gauge widget. State maps -40°C to +40°C onto 0.0 to 1.0.

| Entity | State | Attributes |
|---|---|---|
| `sensor.ec_temp_gauge` | 0.0 to 1.0 | `value`, `low`, `high` |
| `sensor.ec_feels_gauge` | 0.0 to 1.0 | `value`, `low`, `high` |

## Weather entity

| Entity | Purpose |
|---|---|
| `weather.ec_weather` | Native `WeatherEntity` for HA companion app widgets |
