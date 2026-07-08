# Configuration

[← Back to README](../README.md)

## Initial setup

1. Settings → Integrations → Add Integration → "Environment Canada Weather"
2. Search your city ("Ottawa", "Vancouver", "Montréal", etc.)
3. Pick the right match if there are several
4. Check the auto-detected settings (AQHI station, bounding boxes) and adjust if needed
5. Confirm

## Editing settings later

Settings → Integrations → EC Weather → Configure.

| Setting | What it does |
|---|---|
| City code | EC city identifier (e.g. `qc-68` for Saint-Jérôme) |
| Language | `en` or `fr` for EC text summaries |
| Alert bounding box | Region polled for active alerts |
| GeoMet WMS bounding box | Region used for precipitation and temperature queries |
| AQHI station ID | Closest air quality station |
| Polling mode | Controls background polling vs on-demand refresh. See [Polling & API usage](polling.md) |
| Refresh intervals | Per-data-type cadence (weather, AQHI, forecast detail) |
| Extended 14-day forecast | Off by default. Adds 7 dimmed outlook days past the official EC forecast. The extra days are less precise estimates from longer-range models. |

The integration reloads itself when you save.

## Polling modes (quick reference)

| Mode | Use when |
|---|---|
| Minimal (default) | You open the dashboard occasionally |
| Efficient | You use iOS lock screen widgets or have automations on temperature / AQHI |
| Full | You want everything always current, or you log weather data |

Alerts always poll every 30 minutes regardless of mode.

Full details in [Polling & API usage](polling.md).
