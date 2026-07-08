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
| `daily` | 7-day rows with day/night icons, POP + amounts, and temperature range bars colored by absolute temperature. Tap a day for a detail overlay (wind, humidity, UV, precipitation amounts, hourly timeline). When the forecast range is set to 10 or 14 days, the days past 7 render as muted model-outlook rows and tap open a summary popup instead of a timeline. See [Extended forecast](#extended-forecast). |

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

## Extended forecast

The `daily` section can reach past Environment Canada's official 7-day forecast.
Set the forecast range to 7 (default), 10, or 14 days in the integration options (see [Configuration](configuration.md)).

EC only publishes official forecasts 7 days out, so the days past 7 are a model outlook derived from the GEPS ensemble, not an official EC forecast.
The card keeps that distinction honest instead of pretending the extra days are as certain as the first week.

Outlook rows render like the official rows but muted, with a small "Model outlook" caption.
Each row shows the ensemble median high and low, the ensemble POP (hidden below 30 percent, since below that it is measured base-rate noise), and a day and night icon from the same ensemble recipe used across the far days.
Tapping an outlook day opens a summary popup rather than an hourly timeline: an "Outlook" badge, a plain-language sentence ("Likely 22-27°, around 40% chance of rain") whose range widens with distance to carry the growing uncertainty, slimmed Day and Night boxes (icon, median temperature, feels-like, per-half POP, and an amount band when POP is at least 50 percent), and a footnote explaining that the outlook comes from model ensembles.
Humidity, wind, condition text, UV, and AQHI are absent on outlook days by design, because they are not honestly rebuildable that far out.

The section header label follows the range automatically ("7-day", "10-day", or "Outlook").

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
| `--ec-weather-outlook-opacity` | `0.72` | Opacity of the muted model-outlook daily rows (days past 7) |
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
