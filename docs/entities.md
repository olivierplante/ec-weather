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
| `sensor.ec_daily_forecast` | Last update timestamp | `forecast`: daily list with day/night split, timesteps (see below) |
| `sensor.ec_weather_summary` | e.g. "-8° · Feels -11° · Mostly Cloudy" | Diagnostic |

### Daily forecast attribute

Each item in the `forecast` list is one calendar day. The keys vary by how far out the day is.

Official days (0 to 6) carry the full day/night split: `precip_prob_day` / `precip_prob_night`, `rain_mm_*`, `snow_cm_*`, `timesteps_day` / `timesteps_night`, and a `timesteps_state`.

`timesteps_state` is a tri-state that disambiguates an empty timeline:

- `loaded`: timesteps are present.
- `pending`: the day has not been fetched yet.
- `unavailable`: the day was fetched but has no timesteps (past the RDPS-WEonG 84-hour horizon).
- `outlook`: an outlook day (beyond the official 7) that has no timeline by design.

`precip_windows` is present only on the extended GEPS days (4 to 6). It is a list of 12-hour windows, each with `start`, `end`, `pop`, and the `amount_p25` / `amount_p75` band, used by the card's future-spanning precip vessels.

When the extended forecast is enabled, the last official day's missing overnight low (EC publishes the 7th day's night period later in the day) is filled from the GEPS model outlook so its row is not left half empty.

Outlook days (7 and beyond, only when the forecast range is 10 or 14) carry `source: "outlook"`, `timesteps_state: "outlook"`, and no timeline. They add `temp_low` / `temp_high` (ensemble medians), a `temp_range` object (`low` = p25 low, `high` = p75 high) for the widening uncertainty band, `pop_day` / `pop_night` (with `pop_day_display` / `pop_night_display` applying the 30 percent hide rule), `icon_day` / `icon_night`, `feels_like_day` / `feels_like_night`, an `amount_band` when a half-day is wet, and a `sentence` object (`range_low`, `range_high`, `dominant_pop`, `amount_band`) that the card interpolates into the localized outlook sentence.

## Alerts

| Entity | State |
|---|---|
| `binary_sensor.ec_alert_active` | on/off |
| `sensor.ec_alert_count` | Integer, diagnostic |
| `sensor.ec_alerts` | Highest alert type; `alerts` attribute is the full list |

Alerts survive transient network failures by retaining the last-known-good set until each alert's EC-declared expiration, so a dropped fetch cycle never blanks an active alert.

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
