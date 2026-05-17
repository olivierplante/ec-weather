# EC Weather

Weather integration for Home Assistant using Environment Canada's APIs. Includes a built-in Lovelace card. English and French.

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/olivierplante/ec-weather)](https://github.com/olivierplante/ec-weather/releases)

<p>
  <img src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/weather-panel.png" alt="Weather Panel" width="300">
</p>

## What you get

- Current conditions, 48h hourly forecast, 7-day daily forecast
- Active weather alerts for your area
- Air quality (AQHI) with risk level
- A Lovelace card that auto-registers, nothing to set up
- Card renders in ~2 seconds, then fills in detailed data in the background

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olivierplante&repository=ec-weather&category=integration)

1. Click the badge above (or search "Environment Canada Weather" in HACS) and download the integration
2. Restart Home Assistant
3. Settings → Integrations → Add Integration → "Environment Canada Weather"
4. Search for your city and confirm the settings

## Docs

- [Configuration](https://github.com/olivierplante/ec-weather/blob/main/docs/configuration.md): location, options, polling modes
- [Entity reference](https://github.com/olivierplante/ec-weather/blob/main/docs/entities.md): sensors and attributes
- [Lovelace card](https://github.com/olivierplante/ec-weather/blob/main/docs/card.md): sections, full panel, theming
- [Polling & API usage](https://github.com/olivierplante/ec-weather/blob/main/docs/polling.md): tiered loading and caching

## Support

[Report an issue](https://github.com/olivierplante/ec-weather/issues) · [MIT License](https://github.com/olivierplante/ec-weather/blob/main/LICENSE)

Weather data comes from [Environment and Climate Change Canada](https://weather.gc.ca/), a free public service. Be responsible with it: stick to Minimal or Efficient polling unless you need Full.
