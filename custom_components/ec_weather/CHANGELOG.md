# Changelog

## 1.5.4
- Fix manifest key ordering for hassfest compliance

## 1.5.3
- Add brand icon, issue tracker, and validation workflows for HACS submission
- Add CONFIG_SCHEMA for hassfest compliance

## 1.5.2
- Add HACS and hassfest validation workflows

## 1.5.1
- Migrate weather panel from YAML templates to custom Lovelace card (ec-weather-card)
- Add built-in daily forecast popup (replaces browser_mod dependency)
- Add mobile full-screen popup with swipe-down-to-close
- Add options flow for editing settings after install
- Auto-detect nearest city from HA home location during setup
- Add CSS custom properties for theming
- Remove sun.sun dependency (uses ec_sunrise/ec_sunset instead)

## 1.0.0
- Initial release
- Environment Canada weather integration with 4 data coordinators
- Current conditions, hourly (48h) and daily (7-day) forecasts
- Weather alerts, AQHI air quality, sunrise/sunset
- WEonG precipitation enrichment via GeoMet WMS
