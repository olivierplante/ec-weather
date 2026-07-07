/**
 * Render-path smoke tests: every section renders end-to-end against a
 * realistic hass stub. The pure-helper tests can't catch dangling
 * references inside the render methods (a ReferenceError in _renderDaily
 * shipped as 'Configuration error' on the live dashboard) — these can.
 */

import { beforeAll, describe, expect, it } from "vitest";

import { ECWeatherCard } from "../ec-weather-card.js";

beforeAll(() => {
  customElements.define("ec-weather-card", ECWeatherCard);
});

const state = (value, attributes = {}) => ({
  state: String(value),
  attributes,
  last_updated: new Date().toISOString(),
});

const DAILY_FORECAST = [
  // Tonight-only first period (dropped high) — the dot case. Day half has
  // passed (icon_code null), so the popup dims its Day card to "Day is over".
  {
    period: "Tonight", date: "2026-07-04", icon_code: null, icon_code_night: 30,
    temp_high: null, temp_low: 16, precip_prob_night: 0,
    condition_night: "Partly cloudy",
    text_summary_night: "Partly cloudy. Becoming clear this evening. Low 16.",
    wind_speed_night: 20, wind_gust_night: 0, wind_direction_night: "NW",
    updated: "2026-07-04T23:31:00Z",
  },
  {
    period: "Sunday", date: "2026-07-05", icon_code: 0, icon_code_night: 30, temp_high: 29, temp_low: 15, precip_prob_day: 60,
    feels_like_high: 34, feels_like_low: 12, humidity: 55, humidity_night: 80, uv_index: 9, uv_category: "very high",
  },
  { period: "Monday", date: "2026-07-06", icon_code: 12, icon_code_night: 30, temp_high: 22, temp_low: 14, precip_prob_day: 70, rain_mm_day: 5 },
  // Isolated missing temps — nothing to place on the bar.
  { period: "Tuesday", date: "2026-07-07", icon_code: 1, icon_code_night: 30, temp_high: null, temp_low: null },
  // Fetched-but-empty day (GDPS-WEonG removed) → popup shows the unavailable line.
  { period: "Wednesday", date: "2026-07-08", icon_code: 1, icon_code_night: 30, temp_high: 24, temp_low: 13, timesteps_day: [], timesteps_night: [], timesteps_state: "unavailable" },
  // Loaded day with real timesteps → popup shows the hourly timeline.
  {
    period: "Thursday", date: "2026-07-09", icon_code: 12, icon_code_night: 30, temp_high: 20, temp_low: 12, timesteps_state: "loaded",
    timesteps_day: [
      { time: "2026-07-09T14:00:00Z", temp: 19, icon_code: 12, feels_like: 20, precipitation_probability: 40, rain_mm: 1, snow_cm: null },
      { time: "2026-07-09T15:00:00Z", temp: 20, icon_code: 1, feels_like: 21, precipitation_probability: 10, rain_mm: null, snow_cm: null },
    ],
    timesteps_night: [],
  },
];

const HOURLY_FORECAST = [
  { time: "2026-07-04T23:00:00Z", temp: 25, icon_code: 30, feels_like: 27, precipitation_probability: 0, rain_mm: null, snow_cm: null },
  { time: "2026-07-05T00:00:00Z", temp: null, icon_code: 31, feels_like: null, precipitation_probability: 20, rain_mm: 1, snow_cm: null },
  // Isolated temp between gaps.
  { time: "2026-07-05T01:00:00Z", temp: 22, icon_code: null, feels_like: null, precipitation_probability: null, rain_mm: null, snow_cm: null },
  { time: "2026-07-05T02:00:00Z", temp: null, icon_code: null, feels_like: null, precipitation_probability: null, rain_mm: null, snow_cm: null },
];

const buildHass = () => ({
  language: "en",
  themes: { darkMode: true },
  locale: { time_format: "24" },
  config: { latitude: 45.5 },
  callService: () => {},
  states: {
    "sensor.ec_temperature": state("25.8", { fetched_at: new Date().toISOString() }),
    "sensor.ec_feels_like": state("27.0"),
    "sensor.ec_wind_speed": state("13"),
    "sensor.ec_wind_gust": state("29"),
    "sensor.ec_wind_direction": state("NW"),
    "sensor.ec_condition": state("Mainly sunny"),
    "sensor.ec_icon_code": state("1"),
    "sensor.ec_humidity": state("37"),
    "sensor.ec_sunrise": state("05:11"),
    "sensor.ec_sunset": state("20:49"),
    "sensor.ec_air_quality": state("3"),
    "sensor.ec_yesterday_precipitation": state("unknown", { published: false, data_type: "combined" }),
    "sun.sun": state("above_horizon"),
    "binary_sensor.ec_alert_active": state("on"),
    "sensor.ec_alerts": state("1", {
      alerts: [{ type: "statement", headline: "special weather statement", text: "Details.", expires: "2026-07-05T12:00:00Z" }],
    }),
    "sensor.ec_hourly_forecast": state("ok", { forecast: HOURLY_FORECAST }),
    "sensor.ec_daily_forecast": state("ok", { forecast: DAILY_FORECAST }),
  },
});

const renderCard = (section) => {
  const card = document.createElement("ec-weather-card");
  card.setConfig({ section });
  card.hass = buildHass();
  return card;
};

const renderSection = (section) => renderCard(section).shadowRoot;

describe("render smoke — every section renders without throwing", () => {
  it("alerts", () => {
    const root = renderSection("alerts");
    expect(root.querySelectorAll(".alert-wrap")).toHaveLength(1);
    expect(root.innerHTML).toContain("Special Weather Statement");
  });

  it("current", () => {
    const root = renderSection("current");
    expect(root.innerHTML).toContain("26°");
    expect(root.innerHTML).toContain("feels like 27°");
    // Yesterday opted-in but unpublished → No data row.
    expect(root.innerHTML).toContain("No data");
    // AQHI 3 renders (low), sun arc present.
    expect(root.innerHTML).toContain("AQHI");
    expect(root.querySelector(".mcell.sun")).not.toBeNull();
  });

  it("hourly", () => {
    const root = renderSection("hourly");
    expect(root.querySelectorAll(".ecs-col").length).toBeGreaterThan(0);
    // The all-null hour is filtered out: 4 raw → 3 rendered columns.
    expect(root.querySelectorAll(".ecs-col")).toHaveLength(3);
    // Isolated point renders a dot.
    expect(root.querySelectorAll("svg circle").length).toBeGreaterThan(0);
  });

  it("daily", () => {
    const root = renderSection("daily");
    const rows = root.querySelectorAll(".drow");
    expect(rows).toHaveLength(6);
    // Tonight-only period: low shown, high blank, dot on the bar.
    expect(rows[0].querySelector(".dlow").textContent).toBe("16°");
    expect(rows[0].querySelector(".dhigh").textContent).toBe("");
    expect(rows[0].querySelector(".ddot")).not.toBeNull();
    // Full row: both temps and a gradient span.
    expect(rows[1].querySelector(".dhigh").textContent).toBe("29°");
    expect(rows[1].querySelector(".dspan")).not.toBeNull();
    // No temps at all: no bar marks.
    expect(rows[3].querySelector(".dspan")).toBeNull();
    expect(rows[3].querySelector(".ddot")).toBeNull();
  });

  it("daily — wet rows render precip both as the column and the floating label; dry rows neither", () => {
    const rows = renderSection("daily").querySelectorAll(".drow");
    // Sunday (index 1) is wet (60% POP): both the .dprecip column and the
    // in-bar .dfloat carry the POP%.
    const wet = rows[1];
    expect(wet.querySelector(".dprecip").textContent).toContain("%");
    const float = wet.querySelector(".dbar .dfloat");
    expect(float).not.toBeNull();
    expect(float.textContent).toContain("%");
    // Tuesday (index 3) is dry: the precip column is still emitted EMPTY so
    // every row's range bar shares one length/scale (user feedback — the
    // DC's dry-day omission misaligned the bars); no floating label.
    const dry = rows[3];
    const dryCol = dry.querySelector(".dprecip");
    expect(dryCol).not.toBeNull();
    expect(dryCol.textContent).toBe("");
    expect(dry.querySelector(".dfloat")).toBeNull();
    // The low/bar/high form one .dtemps group so min/max always align.
    const temps = wet.querySelector(".dtemps");
    expect(temps).not.toBeNull();
    expect(temps.querySelector(".dlow")).not.toBeNull();
    expect(temps.querySelector(".dbar")).not.toBeNull();
    expect(temps.querySelector(".dhigh")).not.toBeNull();
  });

  it("hourly — the trend line strokes the temperature gradient", () => {
    const root = renderSection("hourly");
    expect(root.innerHTML).toContain('id="ecs-curve-stroke"');
    expect(root.innerHTML).toContain('stroke="url(#ecs-curve-stroke)"');
  });

  it("daily popup — Tonight: passed Day card, night low, narrative, footer", () => {
    const card = renderCard("daily");
    const popups = card._dailyPopups;
    expect(popups).toBeTruthy();
    const tonight = popups[0].content;
    // Day half already passed → dimmed card with "Day is over", no empty dash+°.
    expect(tonight).toContain("Day is over");
    expect(tonight).toContain("ecp-passed");
    // Night card carries the low.
    expect(tonight).toContain("16°");
    // Narrative kept verbatim.
    expect(tonight).toContain("Becoming clear this evening");
    // Footer attribution.
    expect(tonight).toContain("Environment Canada");
  });

  it("daily popup — Sunday period cards surface feels-like, humidity, and Day UV", () => {
    const sunday = renderCard("daily")._dailyPopups[1].content;
    // Feels-like line (Day: 34° differs from the 29° high).
    expect(sunday).toContain("Feels like 34°");
    // Humidity line, lowercased like the metric bar.
    expect(sunday).toContain("55% humidity");
    // UV line only on the Day card, color-coded by the risk scale (9 → very-high).
    expect(sunday).toContain("UV 9");
    expect(sunday).toContain("var(--ec-weather-uv-very-high, #d1495b)");
    expect(sunday).toContain("(very high)");
    // UV renders once — the Day card only, never the Night card.
    expect(sunday.match(/white-balance-sunny/g)).toHaveLength(1);
  });

  it("daily popup — unavailable day shows the dashed placeholder", () => {
    const popups = renderCard("daily")._dailyPopups;
    // Wednesday: fetched-but-empty → the no-hourly placeholder line.
    const unavailable = popups[4].content;
    expect(unavailable).toContain("isn’t available for this day yet");
    expect(unavailable).toContain("ecp-noh");
    // No timeline chart when there's no hourly series.
    expect(unavailable).not.toContain("<svg");
  });

  it("daily popup — loaded day renders the hourly timeline", () => {
    const popups = renderCard("daily")._dailyPopups;
    // Thursday: real timesteps → curve svg + per-hour columns + time labels.
    const loaded = popups[5].content;
    expect(loaded).toContain("<svg");
    expect(loaded).toContain("ecs-col");
    // 24h locale → labels like "HH:00".
    expect(loaded).toContain(":00");
  });
});

describe("compact units — amounts render with NO space everywhere", () => {
  it("daily rows: Monday's 5 mm rain reads 5mm in both column and float", () => {
    const rows = renderSection("daily").querySelectorAll(".drow");
    const monday = rows[2];
    expect(monday.querySelector(".dprecip").textContent).toContain("5mm");
    expect(monday.querySelector(".dfloat").textContent).toContain("5mm");
    expect(monday.textContent).not.toContain("5 mm");
  });

  it("popup period cards: the rain meta line is compact", () => {
    const monday = renderCard("daily")._dailyPopups[2].content;
    expect(monday).toContain("5mm");
    expect(monday).not.toContain("5 mm");
  });

  it("popup timeline fill labels are compact", () => {
    // Thursday's 14:00 timestep carries rain_mm 1 → "1mm".
    const thursday = renderCard("daily")._dailyPopups[5].content;
    expect(thursday).toContain("1mm");
  });
});

describe("wind cell — headline speed+unit, secondary dir · gusts", () => {
  const renderWith = (mutate) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "current" });
    const hass = buildHass();
    mutate(hass.states);
    card.hass = hass;
    return card.shadowRoot;
  };

  it("direction and gusts both present → '13 km/h' over 'NW · gusts 29 km/h'", () => {
    const root = renderSection("current");
    expect(root.innerHTML).toContain("13 km/h");
    expect(root.innerHTML).toContain("NW · gusts 29 km/h");
  });

  it("only direction → secondary is just 'NW'", () => {
    const root = renderWith((states) => {
      states["sensor.ec_wind_gust"] = state("unknown");
    });
    expect(root.innerHTML).toContain("13 km/h");
    expect(root.innerHTML).not.toContain("gusts");
    expect(root.innerHTML).toContain(">NW<");
  });

  it("only gust → secondary is just 'gusts 29 km/h'", () => {
    const root = renderWith((states) => {
      states["sensor.ec_wind_direction"] = state("unknown");
    });
    expect(root.innerHTML).toContain("13 km/h");
    expect(root.innerHTML).toContain(">gusts 29 km/h<");
  });

  it("calm → 'Calm' headline with a reserved blank secondary", () => {
    const root = renderWith((states) => {
      states["sensor.ec_wind_speed"] = state("0");
    });
    expect(root.innerHTML).toContain("Calm");
    expect(root.innerHTML).not.toContain("km/h");
  });

  it("null speed → wind cell hidden entirely", () => {
    const root = renderWith((states) => {
      states["sensor.ec_wind_speed"] = state("unavailable");
    });
    expect(root.innerHTML).not.toContain("mdi:weather-windy");
  });
});

describe("hourly scroll fade — removed by user preference", () => {
  it("no fade overlay anywhere (card or popup)", () => {
    const root = renderSection("hourly");
    expect(root.querySelector(".hfade")).toBeNull();
    expect(renderCard("daily")._dailyPopups[5].content).not.toContain("hfade");
  });
});

describe("sun cell — day/night loop", () => {
  it("arc mode draws the dashed base arc AND the below-horizon dip guide in a 48px box", () => {
    const root = renderSection("current");
    expect(root.innerHTML).toContain("A72,21");
    expect(root.innerHTML).toContain("A72,13");
    expect(root.innerHTML).toContain('viewBox="0 0 168 48"');
  });

  it("caption is the countdown followed by the daylight duration", () => {
    const root = renderSection("current");
    const caption = root.querySelector(".suncap").textContent;
    expect(caption).toMatch(/^(sets in|sunrise in) \d/);
    // Fixture rise 05:11 → set 20:49 = 15h 38m of daylight, after a middot.
    expect(caption).toContain("· 15h 38m of daylight");
  });

  it("a spent trail overlays the elapsed part of the loop", () => {
    // Whatever the wall clock says, one phase trail is present: amber over
    // the day arc or grey over the night dip.
    const html = renderSection("current").innerHTML;
    const dayTrail = html.includes('stroke="var(--ecw-sun)" stroke-width="1.6" stroke-linecap="round" opacity="0.55"');
    const nightTrail = html.includes('stroke="var(--ecw-muted)" stroke-width="1.6" stroke-linecap="round" opacity="0.5"');
    expect(dayTrail || nightTrail).toBe(true);
  });

  const renderPolar = (sunState) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "current" });
    const hass = buildHass();
    hass.config.latitude = 70;
    hass.states["sensor.ec_sunrise"] = state("unknown");
    hass.states["sensor.ec_sunset"] = state("unknown");
    hass.states["sun.sun"] = state(sunState);
    card.hass = hass;
    return card.shadowRoot;
  };

  it("polar day: dot parked at the apex of a SOLID lit arc, 30px box, times hidden", () => {
    const root = renderPolar("above_horizon");
    const html = root.innerHTML;
    expect(html).toContain("Sun up all day");
    // Parked at dayPt(0.5) = (84, 5).
    expect(html).toContain('cx="84" cy="5"');
    expect(html).toContain('viewBox="0 0 168 30"');
    // Lit arc is solid (the polar-day path has no dasharray).
    expect(html).not.toContain("A72,13");
    expect(root.querySelector(".suntimes")).toBeNull();
    // The old subline is retired.
    expect(html).not.toContain("no sunset today");
  });

  it("polar night: dot resting in the dip, base arc + dip guide, times hidden", () => {
    const root = renderPolar("below_horizon");
    const html = root.innerHTML;
    expect(html).toContain("Polar night");
    // Resting at nightPt(0.5) = (84, 39).
    expect(html).toContain('cx="84" cy="39"');
    expect(html).toContain('viewBox="0 0 168 48"');
    expect(html).toContain("A72,13");
    expect(root.querySelector(".suntimes")).toBeNull();
    expect(html).not.toContain("below the horizon");
  });
});
