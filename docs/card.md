# Lovelace card

[← Back to README](../README.md)

The integration ships with `ec-weather-card`. It auto-registers at startup, so you don't need to add it as a resource.

<p>
  <img src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/weather-panel.png" alt="Weather Panel" width="300">
  <img src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/daily-popup.png" alt="Daily Forecast Popup" width="300">
</p>

## Usage

```yaml
type: custom:ec-weather-card
section: current
```

## Sections

| Section | What it shows |
|---|---|
| `alerts` | Alert banners with expand/collapse. Hidden when nothing is active. |
| `current` | Temperature, feels-like, wind, AQHI, condition icon, sun times, daylight remaining. |
| `hourly` | 48-hour scrollable forecast with temp, feels-like, POP, rain/snow. Day separators at midnight. |
| `daily` | 7-day scrollable forecast with day/night icons, temps, precipitation. Tap a day for a detail overlay (wind, humidity, UV, precipitation amounts, hourly timeline). |

## Full panel example

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

## Theming

The card follows your active HA theme automatically. Colors resolve in this order:

1. Any `--ec-weather-*` variable you set yourself
2. The matching HA theme variable
3. A hardcoded dark fallback

| Property | HA theme fallback | Description |
|---|---|---|
| `--ec-weather-text-primary` | `--primary-text-color` | Primary text |
| `--ec-weather-text-secondary` | `--secondary-text-color` | Secondary text |
| `--ec-weather-text-muted` | `--secondary-text-color` | Muted text (feels-like) |
| `--ec-weather-precip-rain` | - | Rain precipitation |
| `--ec-weather-precip-snow` | `--primary-text-color` | Snow precipitation |
| `--ec-weather-alert-warning` | - | Warning alert |
| `--ec-weather-alert-watch` | - | Watch alert |
| `--ec-weather-alert-advisory` | - | Advisory alert |
| `--ec-weather-alert-statement` | `--secondary-text-color` | Statement alert |
| `--ec-weather-divider` | `--divider-color` | Divider line |
