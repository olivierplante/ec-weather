<!-- info.md — this file exists FOR HACS: it renders inside Home Assistant's
     HACS panel, whose markdown engine supports only a subset of GitHub's
     (no <picture>, no admonitions, no <details>) AND turns every newline
     into a line break. Keep this file PLAIN: headings, lists, code blocks,
     images with absolute raw URLs, ONE LINE per paragraph/bullet, no
     em-dashes. GitHub visitors see README.md instead; the full gallery
     lives in docs/screenshots.md. Regenerate images with
     www/screenshot-tool/. -->

![EC Weather Card](https://raw.githubusercontent.com/olivierplante/ec-weather/main/screenshots/overview.webp)

**Environment Canada weather for Home Assistant.** Alerts, current conditions, a 48-hour trend and a 7-day outlook, all from EC's free public APIs. No external dependencies, no API keys.

**Highlights**

- Zero-config Lovelace card: auto-registers, follows your HA theme (dark and light), English and Français
- Feels-like (humidex / wind chill), AQHI and UV color-coded by risk, yesterday's measured precipitation
- 48-hour temperature curve colored on an absolute temperature scale, rain drawn as rising water levels
- 7-day range bars on the week's own scale. Tap a day for the narrative forecast, day/night detail and an hourly timeline

**Setup**

1. Install through HACS, then restart Home Assistant.
2. Add the integration: *Settings → Devices & Services → Add Integration* → *Environment Canada Weather*, and pick your city.
3. Add the card to a dashboard. Each section is its own card, so you can compose them however you like:

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

[More screenshots](https://github.com/olivierplante/ec-weather/blob/main/docs/screenshots.md) · [Full documentation](https://github.com/olivierplante/ec-weather)
