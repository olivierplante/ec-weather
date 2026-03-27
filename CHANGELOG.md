# Changelog

## 1.8.4

**Smarter refresh scheduling** — WEonG data now refreshes when a new HRDPS model run is available (~4x/day) instead of on a fixed 6-hour timer. Opening the dashboard after a new model run triggers an immediate fetch. The configurable WEonG interval setting has been removed — it's now automatic.

**Full polling mode** — In full polling mode, WEonG schedules polls dynamically based on the HRDPS model run schedule. If data is delayed, retries every 15 minutes until available.

**Accurate "Updated at" timestamp** — Now reflects when GeoMet data was actually fetched, not when it was last projected internally.

**Translation system** — "Updated at" label now uses the i18n system instead of hardcoded strings.

## 1.8.3

**Tonight forecast restored** — The "Tonight" period was being hidden in the evening when it should only be filtered during daytime (6 AM–6 PM). Now correctly shown after 6 PM when EC issues a fresh Tonight forecast.

**Hourly icons for all hours** — Icons for hours 25–48 (beyond EC hourly coverage) were missing until a daily popup was opened. SkyState is now fetched in the background sweep so icons appear immediately. Also fixes missing icons for timesteps with precipitation probability but no accumulation (e.g., 40% POP, 0 mm).

**Accurate "Updated at" timestamp** — Each daily popup now shows when its data was last fetched, using the oldest of the EC and GeoMet timestamps. Previously showed the EC fetch time even when the popup data came from GeoMet.

## 1.8.2

Add MIT license. Release pipeline now uses PRs with CI checks before publishing.

## 1.8.1

**CI fix** — Fixed test file path resolution for GitHub Actions. Tests now resolve the JS card file from the Python package location instead of hardcoded paths, working correctly in both local and CI environments.

**Release pipeline** — Releases now go through a PR with CI checks before publishing. Previously, releases were pushed directly to GitHub without waiting for tests to pass.

## 1.8.0

**Instant loading** — The card now renders immediately from Environment Canada data (~2 seconds). Precipitation probabilities and amounts load in the background and fill in automatically. Previously, the card waited for all data before showing anything (~7 seconds).

**French language support** — Full bilingual support (English/French). The card, entity names, and weather conditions follow your Home Assistant language setting. Day names, time format (12h/24h), and all labels adapt automatically.

**Device registry** — All entities are now grouped under a single "EC Weather" device in Settings → Devices. Makes it easier to find and manage all weather entities.

**Smarter API usage** — The integration now tracks Environment Canada's model run schedule and only re-fetches data when new forecasts are actually available. Popup timeline data loads only when you open a popup. Reduces unnecessary API calls significantly.

**Under the hood** — Major internal refactor for long-term reliability. The data pipeline was rebuilt around a single source of truth for all forecast timesteps, replacing a dual-data-path system that could lose data during refreshes. This fixes intermittent issues where popup icons or temperatures would briefly disappear. The codebase was restructured into smaller, focused modules — easier to maintain and extend going forward.

**Daily popup improvements:**
- "Updated" timestamp shows when the data was last refreshed
- Stale "Tonight" period is hidden after 6 AM
- Empty alerts from EC are filtered out

**Alert dropdown fix** — The alert expand/collapse now works on the first click.

**Security** — All text from EC APIs is now HTML-escaped before rendering.

**Tests** — 347 tests (up from 89), covering all data paths, config flow, and edge cases.

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
