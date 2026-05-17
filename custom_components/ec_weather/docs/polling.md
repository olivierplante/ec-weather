# Polling & API usage

[← Back to README](../README.md)

Environment Canada's APIs are free and open, paid for with public money. The integration caches data against the real model-run schedule, so refreshes between runs hit local memory instead of EC servers. Stick to Minimal or Efficient unless you genuinely need Full.

## Tiered loading

| Tier | What loads | When | API calls |
|---|---|---|---|
| Instant | Current conditions, hourly (24h), daily icons / temps / precip amounts | Dashboard open | 1 EC API call |
| Background | Hourly extends to 48h, daily gets POP%, rain/snow totals | 3-5s after render | ~200 GeoMet queries |
| On popup open | Per-timestep SkyState icons for the selected day | User taps a day | ~8-20 queries (cached) |

After the first load, queries are served from cache until EC publishes a new model run:

- HRDPS (high-resolution, 2.5 km): every 6 hours
- GDPS (global, 15 km): every 12 hours

## Polling modes

Set in Settings → Integrations → EC Weather → Configure → Polling mode.

### Minimal (default)

Only alerts poll continuously (every 30 minutes). Everything else refreshes when you open the dashboard.

Use this if you mostly check the weather by opening the dashboard.

### Efficient

Alerts + current conditions + AQHI poll continuously. Forecasts still refresh on-demand.

Use this for iOS lock screen widgets, temperature-driven automations, or AQHI alerts.

### Full

Everything polls continuously, including forecast detail from GeoMet WMS.

Use this if you want everything always current or you log weather data.

## Alerts override the mode

Alerts poll every 30 minutes in every mode. This isn't configurable. Alert-based automations need to fire on time.
