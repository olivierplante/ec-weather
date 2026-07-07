# Lovelace card

[← Back to README](../README.md)

The integration ships with `ec-weather-card`. It auto-registers at startup, so you don't need to add it as a resource.

<picture>
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/dashboard-light.png">
  <img alt="Dashboard" src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/dashboard.png">
</picture>

<picture>
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/popup-light.png">
  <img alt="Day detail popup" src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/popup.png">
</picture>

## Usage

```yaml
type: custom:ec-weather-card
section: current
```

## Sections

| Section | What it shows |
|---|---|
| `alerts` | Neutral alert bars (one style for every warning type) with expand/collapse. Hidden when nothing is active. |
| `current` | Hero (temperature, condition, feels-like), precipitation panel (today's chance + amounts, optional yesterday), metric bar (humidity · wind · AQHI · UV · sun arc). |
| `hourly` | 48-hour scrollable trend: temperature curve, POP + rain/snow amounts with bars, per-day bands. |
| `daily` | 7-day rows with day/night icons, POP + amounts, and temperature range bars colored by absolute temperature. Tap a day for a detail overlay (wind, humidity, UV, precipitation amounts, hourly timeline). |

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

Weather accents (rain, snow, sun, curve…) are design literals tuned per
theme (dark and light sets); the neutral tokens bind to your HA theme
variables. Your `--ec-weather-*` override always wins in both themes.

| Property | HA theme fallback | Description |
|---|---|---|
| `--ec-weather-text-primary` | `--primary-text-color` | Primary text |
| `--ec-weather-text-secondary` | `--secondary-text-color` | Secondary text |
| `--ec-weather-text-muted` | `--secondary-text-color` | Muted text (feels-like, captions) |
| `--ec-weather-divider` | `--divider-color` | Hairlines and dividers |
| `--ec-weather-precip-rain` | - | Rain accent (chips, bars, amounts) |
| `--ec-weather-precip-snow` | - | Snow accent (chips, amounts) |
| `--ec-weather-snow-bar` | - | Snow bar segments |
| `--ec-weather-sun` | - | Sun accent (arc dot, sunny icons) |
| `--ec-weather-sun-arc` | - | Sunrise→sunset arc stroke |
| `--ec-weather-curve` | - | Hourly temperature curve |
| `--ec-weather-pop` | - | Probability-of-precipitation text |
| `--ec-weather-hero-icon` | `--primary-text-color` | Hero condition icon |
| `--ec-weather-alert-border` | - | Alert bar border |
| `--ec-weather-panel-bg` / `-border` / `-head` / `-title` | - | Precipitation panel |
| `--ec-weather-temp-frigid` … `-scorching` | - | The 8 absolute-temperature bucket colors (range bars) |
| `--ec-weather-aqhi-low` / `-moderate` / `-high` / `-very-high` | - | AQHI risk colors |
| `--ec-weather-uv-low` / `-moderate` / `-high` / `-very-high` / `-extreme` | - | UV risk colors |

### Removed in the redesign

Alert bars now use one neutral style for every warning type, so the
per-severity variables (`--ec-weather-alert-warning`, `-watch`,
`-advisory`, `-statement`) and `--ec-weather-alert-bg` are no longer
read. Setting them has no effect.
