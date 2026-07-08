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

- HRDPS-WEonG (high-resolution, 2.5 km, to 48h): every 6 hours
- RDPS-WEonG (regional, 10 km, to 84h): every 6 hours
- GEPS ensemble (extended days 4-6, 3-hour popup steps): every 12 hours (00Z and 12Z runs, ~5-6 hour publish lag)

The GEPS extended wave runs beside the WEonG sweep and fills the day 4-6 popup timelines that the deterministic 84-hour horizon cannot reach. Its 12-hour cache means one extended fetch per GEPS run, not one per WEonG refresh, so it adds no extra load on Minimal or Efficient. GEPS days are also fetched on demand when you open a day 4-6 popup.

## Outlook query counts (forecast range)

When the forecast range is set past 7 days, each GEPS run also fetches the outlook days (the muted rows beyond day 7). GEPS runs twice a day (00Z and 12Z), and the 12-hour cache means these counts are per run, not per refresh.

| Forecast range | Extra GEPS outlook queries per run |
|---|---|
| 7 days (default) | none |
| 10 days | ~30-54 (3 outlook days) |
| 14 days | ~70+ (7 outlook days) |

Each outlook day costs about ten queries (temperature medians and the warm/cold band, humidex, cloud, and two 12-hour POP windows), plus a few more for the amount band and precip type when a half-day is wet. The counts only apply to the users who opt into 10 or 14 days.

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
