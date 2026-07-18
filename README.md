<h1 align="center">EC Weather</h1>

<p align="center">Weather integration for Home Assistant using Environment Canada's APIs, with a built-in Lovelace card. Works with any Canadian location Environment Canada serves. English and French.</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Default-41BDF5.svg" alt="HACS Default"></a>
  <a href="https://github.com/olivierplante/ec-weather/releases"><img src="https://img.shields.io/github/v/release/olivierplante/ec-weather" alt="GitHub Release"></a>
  <a href="https://github.com/olivierplante/ec-weather/actions/workflows/validate.yml"><img src="https://github.com/olivierplante/ec-weather/actions/workflows/validate.yml/badge.svg" alt="CI"></a>
</p>

<p align="center">
  <img alt="EC Weather Card" src="https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/overview.webp">
</p>

<p align="center"><a href="https://github.com/olivierplante/ec-weather/blob/main/docs/screenshots.md">More screenshots</a></p>

## What you get

- Current conditions, a 48-hour hourly trend and a 7-day outlook
- Active weather alerts for your area, with optional AI grouping of related alerts (beta)
- Feels-like (humidex / wind chill), AQHI and UV color-coded by risk
- A Lovelace card that auto-registers, follows your HA theme (dark and light), English and Français
- Renders in ~2 seconds, then fills in detailed data in the background

## Beta features

Some settings live in a collapsed "Beta" section at the bottom of the configure dialog. These are features being tested in the open before they become official: they are always off by default, they may change substantially or be removed in a later release, and they may not work perfectly yet. Turning them off always returns the integration to its stable behaviour. Feedback through GitHub issues is welcome.

The current beta features are described in [Configuration](https://github.com/olivierplante/ec-weather/blob/main/docs/configuration.md) and, for the AI ones, in [AI features](https://github.com/olivierplante/ec-weather/blob/main/docs/ai.md).

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
- [Screenshots](https://github.com/olivierplante/ec-weather/blob/main/docs/screenshots.md): desktop, mobile, popup, light theme
- [Polling & API usage](https://github.com/olivierplante/ec-weather/blob/main/docs/polling.md): tiered loading and caching
- [AI features (beta)](https://github.com/olivierplante/ec-weather/blob/main/docs/ai.md): optional AI grouping of related alerts

## Support

[Report an issue](https://github.com/olivierplante/ec-weather/issues) · [MIT License](https://github.com/olivierplante/ec-weather/blob/main/LICENSE)

Weather data comes from [Environment and Climate Change Canada](https://weather.gc.ca/), a free public service. Be responsible with it: stick to Minimal or Efficient polling unless you need Full.
