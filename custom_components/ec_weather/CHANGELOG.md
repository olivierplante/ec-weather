# Changelog

## 1.7.0

**Light mode support** — The card now works with any Home Assistant theme out of the box. Text, icons, backgrounds, and overlays automatically adapt to your active theme (light or dark). No configuration needed.

Previously, all colors were hardcoded for dark backgrounds, making the card unreadable on light themes. Now, the card reads HA's built-in theme variables (`--primary-text-color`, `--secondary-text-color`, etc.) and falls back to dark defaults only as a last resort.

**New CSS variable** — `--ec-weather-alert-bg` lets you customize the alert banner background independently.

**Theming improvements:**
- Alert banner now has a visible background and border on all themes
- Snow precipitation color adapts to theme instead of being hardcoded white
- Overlay/popup backgrounds adapt to theme
- All 11 CSS custom properties documented with their HA theme fallback chain

No breaking changes. Existing dark theme setups and custom `--ec-weather-*` overrides continue to work unchanged.

## 1.6.4

**Faster dashboard loading** — The weather panel now loads progressively. Current conditions and alerts appear in ~2 seconds. Hourly and daily forecasts fill in shortly after. Daily popup timeline icons load when you open the popup.

**Polling modes** — New setting to control how often data is fetched from Environment Canada:
- **Minimal** (default) — only alerts poll. ~48 API calls/day
- **Efficient** — adds conditions and AQHI for iOS widgets and automations. ~104 calls/day
- **Full** — everything polls continuously. ~1,024 calls/day
- Previously: ~7,300 calls/day regardless of usage

**Configurable refresh intervals** — New settings in integration options: weather conditions (10–120 min, default 30), AQHI air quality (1–12h, default 3), forecast detail (1–12h, default 6).

**Reliability** — Automatic retry on DNS and network failures. "Weather data unavailable" banner with retry button. Failed network requests no longer get cached — data recovers on next refresh.

**Daily popup** — Weather icons now appear for all 7 forecast days. Timeline icons load on-demand when you open the popup.

**Bug fixes** — Fix blank weather icons at current hour. Fix database warning about forecast data size. Fix repeated "no night period" log warnings.

**Unit tests** — 77 tests run on every release via GitHub Actions.

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
