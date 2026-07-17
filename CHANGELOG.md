# Changelog

## 2.4.0

Smarter alerts, honest precipitation, and a card that fits anywhere.

### What's new

- **Group related alerts with AI (beta).** Environment Canada often publishes several alerts for one weather event, a severe thunderstorm warning alongside its watch, for example. When enabled, an AI Task decides which alerts describe the same event and the card shows one alert with its related bulletins nested inside. Nothing is ever hidden or dropped, and any AI problem simply shows the alerts ungrouped. Requires Home Assistant 2025.7+ and an AI Task entity (Ollama, OpenAI, Anthropic, Google). The default instructions are tuned for small local models and are fully editable if your model judges differently. See the new [AI features](docs/ai.md) documentation
- **Duplicate alerts are merged.** The same alert issued for several neighbouring forecast zones now collapses to one, always, no AI involved
- **A Beta section in the options.** Experimental settings now live in a collapsed Beta section of the configure dialog. They are opt-in, may change between releases, and can be disabled at any time
- **Honest daily precipitation amounts.** The daily forecast now shows an amount only when Environment Canada states one. The previous behaviour could display inflated totals built from hourly model data on days with a low chance of precipitation. If you want a model-based estimate back, the new "Estimated precipitation amounts" beta option shows a probability-weighted total, marked with a tilde to distinguish it from amounts Environment Canada states, and hides trace amounts as noise
- **Tonight shows a real temperature range.** Evening rows used to show a single point on the temperature bar; they now derive their range from the hourly forecast

### Fixed

- The precipitation outlook in the daily popup could keep showing an outdated ensemble band after the day moved into higher-resolution coverage, and could lag behind Environment Canada's newest model run. Both fixed; outlook bands now always reflect the latest published run
- The 14-day list now adapts cleanly to narrow dashboard columns: content no longer overflows or sits off-centre, day labels align with the section title, winter temperatures and mixed rain-and-snow labels fit, and the temperature bars keep their width. Wider layouts are unchanged
- French dashboards abbreviate "Aujourd'hui" to "Ajd" in the day list so the label never crowds the row


## 2.3.1

Alert reliability and polish.

### Fixed

- Active alerts no longer disappear from the card when a forecast refresh hits a temporary network problem. The card keeps showing the last known alerts until they reach the expiration time Environment Canada declared for them, so a brief connection blip can never blank an active warning
- A little more breathing room below the alert banner, and the spacing now holds inside stack-in-card wrappers


## 2.3.0

The card now finds its entities by itself.

### What's new

- The card no longer depends on fixed entity IDs. It asks the integration directly which entities to read, so fresh installs, reinstalls, and renamed entities all just work. This permanently ends the "Weather data unavailable" problem reported in issue #12
- You can rename any EC Weather entity freely and the card keeps working. This release never changes your existing entity IDs
- Entity names are now translated: French installs get French names (Température, Ressenti, and so on) and English names lose the redundant "EC" prefix, since entities already sit under the EC Weather device. Names you customized yourself are untouched

### Fixed

- The air quality sensor could sit at "unknown" forever when Environment Canada retired the configured AQHI station. The integration now detects this and switches to the nearest reporting station automatically, at a cost of at most one extra query per day

## 2.2.0

Fewer queries to Environment Canada, and a fix for fresh installs.

### What's new

- The forecast now survives restarts: hourly data is saved to disk and restored on boot, so the card renders within seconds and the integration sends zero new queries when the forecast data is still current. A restart never made the forecast stale; now it doesn't cost a refetch either

### Fixed

- Fresh installs showed "Weather data unavailable" even though the integration was fetching fine: Home Assistant generated entity IDs on new installs that did not match the ones the card reads (reported in issue #12). Affected installs are repaired automatically on update; entity history carries over. If you built automations or dashboards on the old device-prefixed IDs (sensor.ec_weather_yourcity_...), update them to the short form (sensor.ec_temperature and so on). Entities you renamed yourself are left untouched
- During Environment Canada API slowdowns, a restart could lock in half-loaded days for hours: failed queries are no longer cached, partially loaded days keep retrying every 15 minutes, and queries pace themselves and back off when the API rate-limits

## 2.1.0

The forecast now reaches as far as the data honestly allows.

![Desktop, mobile and day detail](https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/overview.webp)

[More screenshots](https://github.com/olivierplante/ec-weather/blob/main/docs/screenshots.md)

### What's new

- Hourly detail is back for days 3 and 4: Environment Canada removed the GDPS data source in early July 2026, and the card now uses the RDPS model (10 km, 84-hour horizon) at full hourly resolution instead of the previous 3-hour blocks
- Days 4 to 6 show a 3-hour timeline again, built from EC's GEPS ensemble: temperatures, feels-like, icons and a real probability of precipitation per half-day window, with rain amounts drawn as blocks spanning the window they belong to
- New option: extended 14-day forecast, off by default. It adds a week of outlook beyond EC's official 7-day forecast. Nobody can predict the exact weather 12 days out, so these days deliberately show less: a likely temperature, the chance of rain and a general sky tendency, dimmed to set them apart from the real forecast. Good for spotting a warm stretch or a wet week ahead, not for planning around a specific hour

### Fixed

- The integration no longer sends hundreds of daily queries to the dataset EC removed
- The HACS page showed a raw picture tag above the screenshot; the README now renders cleanly in HACS

## 2.0.0

Every part of the card has been rebuilt on a single design system.

![Desktop, mobile and day detail](https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/overview.webp)

[More screenshots](https://github.com/olivierplante/ec-weather/blob/main/docs/screenshots.md)

### What's new

- New layout throughout: hero conditions, precipitation panel, metric bar (humidity, wind, AQHI, UV, sun), hourly trend and 7-day range bars
- One temperature language: the hourly curve and the 7-day bars share an absolute temperature color scale
- Rain drawn as rising water levels, with per-hour probability of precipitation
- The sun cell is a day/night loop with a countdown to the next sunrise or sunset
- Day detail popup rebuilt to match: narrative forecast, day/night cards and an hourly timeline, with an honest placeholder when EC has no hourly data
- Yesterday's precipitation sensors, with automatic discovery of the nearest station that actually reports precipitation (closes #9)
- Feels-like now works in hot and humid weather: humidex is parsed from EC and computed locally when EC omits it
- French chrome throughout; the clock follows your HA 12/24-hour setting

### Upgrading

No configuration changes: the four `section:` cards and all entities are unchanged. The card looks completely different after this update. If you had themed the card, several CSS variables changed; see the [theming table](https://github.com/olivierplante/ec-weather/blob/main/docs/card.md#theming).

## 1.8.7

**Documentation links fixed** — The README links to `docs/configuration.md` and the other reference pages were broken in 1.8.6 because the `docs/` folder wasn't copied to the published repo. The folder is now included.

**Integration name consistent across HACS and HA** — HACS now shows the integration as "Environment Canada Weather" instead of "EC Weather", matching what Home Assistant displays after install.

## 1.8.6

**Documentation restructure** — The README is now scoped to what the integration does and how to install it. Reference content (entities, configuration, the Lovelace card, polling and API usage) moved to dedicated pages under `docs/`. No functional changes.

## 1.8.5

**CI** — Updated GitHub Actions to Node.js 24 (`actions/checkout@v6`, `actions/setup-python@v6`).

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
