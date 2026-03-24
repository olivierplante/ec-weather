# EC Weather — Home Assistant Custom Integration

Custom integration that pulls weather data directly from Environment Canada's GeoMet-OGC-API and exposes it as HA sensor entities. Includes a built-in Lovelace card for displaying weather data.

<p>
  <img src="screenshots/weather-panel.png" alt="Weather Panel" width="300">
  <img src="screenshots/daily-popup.png" alt="Daily Forecast Popup" width="300">
</p>

## What it does

- Polls four EC API endpoints on independent schedules
- Exposes current conditions, hourly forecast (24h), daily forecast (7-day with day/night split), weather alerts, yesterday's climate data, and AQHI as native HA entities
- Enriches daily forecasts with precipitation probability from GeoMet WMS (WEonG models)
- Provides a `WeatherEntity` (`weather.ec_weather`) for native HA widget compatibility

## Location config

Location is configured via the HA UI config flow at setup time:

1. **Settings → Integrations → Add Integration → "Environment Canada Weather"**
2. Search for your city name (e.g. "Ottawa", "Vancouver", "Montréal")
3. If multiple matches, select the correct one from the dropdown
4. Review auto-discovered settings (AQHI station, climate station, bounding boxes) and edit if needed
5. Confirm to create the integration

To change location: remove the integration and re-add it.

### Editing settings after installation

Go to **Settings → Integrations → EC Weather → Configure** to edit:
- Language (en/fr)
- Alert bounding box
- GeoMet WMS bounding box
- AQHI station ID
- Polling mode
- Refresh intervals (weather, AQHI, forecast detail)

The integration reloads automatically after saving changes.

### Polling Modes

Controls how the integration fetches data from Environment Canada. Choose the mode that fits how you use it:

**Minimal** (default) — Only weather alerts poll continuously (every 30 minutes). All other data (conditions, forecasts, AQHI) refreshes on-demand when you open the dashboard. Best if you check the weather occasionally. ~48 API calls/day.

**Efficient** — Alerts, current conditions, and AQHI poll continuously at their configured intervals. Forecasts refresh on-demand when the dashboard is viewed. Choose this if you use iOS lock screen widgets, temperature-based automations, or AQHI alerts — these need fresh data even when you're not looking at the dashboard. ~104 API calls/day.

**Full** — Everything polls continuously at configured intervals, including the forecast detail data from GeoMet WMS. Choose this if you want all data always up-to-date, or if you log weather data for analysis. ~1,024 API calls/day.

In all modes, weather alerts always poll every 30 minutes for safety.

### Config entry data

| Key | Example | Purpose |
|---|---|---|
| `city_code` | `on-118` | City page weather API |
| `city_name` | `Ottawa` | Display name |
| `language` | `en` | API language (`en`/`fr`) |
| `lat` / `lon` | `45.42` / `-75.70` | City coordinates |
| `bbox` | `-75.9,45.2,-75.5,45.6` | Weather alerts bounding box |
| `geomet_bbox` | `44.420,-76.700,46.420,-74.700` | GeoMet WMS bounding box (2° box) |
| `aqhi_location_id` | `EAOTT` | AQHI forecast station (auto-discovered, optional) |
| `climate_station_id` | `6105976` | Climate daily station (auto-discovered, optional) |

## Entity inventory

### Current conditions (ECWeatherCoordinator — on-demand, default 30 min)

| Entity | State |
|---|---|
| `sensor.ec_temperature` | °C |
| `sensor.ec_feels_like` | °C (wind chill or humidex) |
| `sensor.ec_humidity` | % |
| `sensor.ec_wind_speed` | km/h |
| `sensor.ec_wind_gust` | km/h (null when absent) |
| `sensor.ec_wind_direction` | Cardinal string (e.g. "NW") |
| `sensor.ec_condition` | Text (e.g. "Mostly Cloudy") |
| `sensor.ec_icon_code` | Integer (0–48) |
| `sensor.ec_sunrise` | "HH:MM" local |
| `sensor.ec_sunset` | "HH:MM" local |
| `sensor.ec_hourly_forecast` | Last update timestamp; `forecast` attribute = 24 items |
| `sensor.ec_daily_forecast` | Last update timestamp; `forecast` attribute = 7 items |
| `sensor.ec_weather_summary` | Formatted string for companion app widget |

### Alerts (ECAlertCoordinator — always polling, 30 min)

| Entity | State |
|---|---|
| `binary_sensor.ec_alert_active` | on/off |
| `sensor.ec_alert_count` | Integer |
| `sensor.ec_alerts` | Highest alert type; `alerts` attribute = list of dicts |

### Air quality (ECAQHICoordinator — on-demand, default 3h)

| Entity | State |
|---|---|
| `sensor.ec_air_quality` | Float (e.g. 3.0); `risk_level` attribute |

### iOS lock screen gauge (ECWeatherCoordinator)

| Entity | State | Attributes |
|---|---|---|
| `sensor.ec_temp_gauge` | Float 0.0–1.0 (gauge arc position) | `value`, `low`, `high` |
| `sensor.ec_feels_gauge` | Float 0.0–1.0 (gauge arc position) | `value`, `low`, `high` |

Pre-computed sensors for the HA Companion App's iOS lock screen gauge widget (Accessory Circular). The state maps -40°C to +40°C onto 0.0–1.0. Attributes are pre-formatted temperature strings (e.g. "-14°").

**Widget configuration** (type these manually in the iOS widget editor):

| Field | Template |
|---|---|
| Value | `{{ states('sensor.ec_temp_gauge') }}` |
| Value label | `{{ state_attr('sensor.ec_temp_gauge', 'value') }}` |
| Min label | `{{ state_attr('sensor.ec_temp_gauge', 'low') }}` |
| Max label | `{{ state_attr('sensor.ec_temp_gauge', 'high') }}` |

For the feels-like gauge, replace `ec_temp_gauge` with `ec_feels_gauge`.

### Weather entity

| Entity | Purpose |
|---|---|
| `weather.ec_weather` | Native WeatherEntity for companion app widgets |

## Update schedules

Intervals depend on the selected polling mode. Default intervals shown below (configurable in settings):

| Data | Default interval | Mode required | Source |
|---|---|---|---|
| Weather alerts | 30 min (always) | All modes | `weather-alerts` API |
| Current conditions | 30 min | Efficient or Full | `citypageweather-realtime` API |
| AQHI air quality | 3 hours | Efficient or Full | `aqhi-forecasts-realtime` API |
| Forecast detail (WEonG) | 6 hours | Full only | GeoMet WMS GetFeatureInfo |

In Minimal mode, conditions/AQHI/forecasts refresh on-demand when the dashboard is viewed.

## Lovelace Card

The integration includes a custom Lovelace card (`ec-weather-card`) that renders weather data with no external dependencies. The card auto-registers at startup — no manual resource configuration needed.

### Usage

```yaml
type: custom:ec-weather-card
section: current
```

### Sections

| Section | Description |
|---------|-------------|
| `alerts` | Weather alert banners with expand/collapse. Hidden when no alerts are active. |
| `current` | Current temperature, feels-like, wind, AQHI, condition icon, sun times, and daylight remaining. |
| `hourly` | Scrollable 48-hour forecast with temperature, feels-like, precipitation probability (rounded to nearest 5%), and rain/snow amounts. Day separators at midnight boundaries. |
| `daily` | Scrollable 7-day forecast with day/night icons, temperatures, feels-like, precipitation. Tap a day for detail overlay with wind, humidity, UV index, and hourly timeline. |

### Full weather panel example

```yaml
type: vertical-stack
cards:
  - type: custom:ec-weather-card
    section: alerts

  - type: custom:ec-weather-card
    section: current

  - type: custom:ec-weather-card
    section: hourly

  - type: custom:ec-weather-card
    section: daily
```

### Theming

The card is **theme-aware** and adapts to any Home Assistant theme (light or dark) automatically. It reads HA's built-in CSS variables (`--primary-text-color`, `--secondary-text-color`, etc.) so colors match your active theme out of the box.

Colors resolve in this order:
1. **Card-specific override** (`--ec-weather-*`) — if set, takes priority
2. **HA theme variable** — adapts to your active theme automatically
3. **Hardcoded fallback** — dark theme defaults as last resort

| Property | HA theme fallback | Final fallback | Description |
|----------|-------------------|----------------|-------------|
| `--ec-weather-text-primary` | `--primary-text-color` | `#FFFFFF` | Primary text color |
| `--ec-weather-text-secondary` | `--secondary-text-color` | `rgba(255,255,255,0.6)` | Secondary text |
| `--ec-weather-text-muted` | `--secondary-text-color` | `rgba(255,255,255,0.45)` | Muted text (feels-like) |
| `--ec-weather-precip-rain` | — | `#4FC3F7` | Rain precipitation color |
| `--ec-weather-precip-snow` | `--primary-text-color` | `rgba(255,255,255,0.85)` | Snow precipitation color |
| `--ec-weather-alert-warning` | — | `#EF5350` | Warning alert color |
| `--ec-weather-alert-watch` | — | `#FFA726` | Watch alert color |
| `--ec-weather-alert-advisory` | — | `#FFEE58` | Advisory alert color |
| `--ec-weather-alert-statement` | `--secondary-text-color` | `rgba(255,255,255,0.6)` | Statement alert color |
| `--ec-weather-alert-bg` | `--card-background-color` | `#0a1520` | Alert banner background |
| `--ec-weather-divider` | `--divider-color` | `rgba(255,255,255,0.06)` | Divider line color |

Backgrounds and overlays also adapt via `--primary-background-color`, `--ha-card-background`, and `--divider-color`.

Example override via theme or card-mod:

```yaml
type: custom:ec-weather-card
section: current
card_mod:
  style: |
    :host {
      --ec-weather-precip-rain: #29B6F6;
    }
```

### Entities consumed

The card reads entities created by the `ec_weather` integration. No configuration of entity IDs is needed.

| Section | Entities |
|---------|----------|
| `alerts` | `binary_sensor.ec_alert_active`, `sensor.ec_alerts` |
| `current` | `sensor.ec_temperature`, `sensor.ec_feels_like`, `sensor.ec_wind_speed`, `sensor.ec_wind_direction`, `sensor.ec_wind_gust`, `sensor.ec_condition`, `sensor.ec_icon_code`, `sensor.ec_air_quality`, `sensor.ec_sunrise`, `sensor.ec_sunset` |
| `hourly` | `sensor.ec_hourly_forecast` |
| `daily` | `sensor.ec_daily_forecast` |

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu (top right) → **Custom repositories**
3. Add the repository URL and select **Integration** as the category
4. Click **Add**, then find **EC Weather** in the HACS integration list
5. Click **Download**
6. Restart Home Assistant

The Lovelace card auto-registers — no separate card installation needed.

### Manual

Copy the `ec_weather` folder to `config/custom_components/` and restart Home Assistant.
