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

// ── Extended forecast (Phase D): outlook rows + summary popups ─────────────

// The first 7 official days plus GEPS outlook rows appended after them. The
// wet outlook day carries an amount band and a full sentence; the dry one has
// a temperature-only sentence (dominant_pop null); the third has a pop but no
// amount band (chance band, no ">= 50" amount line).
const EXT_FORECAST = [
  { period: "Today", date: "2026-07-04", icon_code: 12, icon_code_night: 33, temp_high: 24, temp_low: 17, precip_prob_day: 70, rain_mm_day: 8 },
  { period: "Sunday", date: "2026-07-05", icon_code: 0, icon_code_night: 30, temp_high: 29, temp_low: 16, precip_prob_day: 0 },
  { period: "Monday", date: "2026-07-06", icon_code: 2, icon_code_night: 33, temp_high: 30, temp_low: 17, precip_prob_day: 20 },
  { period: "Tuesday", date: "2026-07-07", icon_code: 12, icon_code_night: 12, temp_high: 22, temp_low: 15, precip_prob_day: 80, rain_mm_day: 12 },
  { period: "Wednesday", date: "2026-07-08", icon_code: 1, icon_code_night: 30, temp_high: 26, temp_low: 13, precip_prob_day: 0 },
  { period: "Thursday", date: "2026-07-09", icon_code: 0, icon_code_night: 30, temp_high: 28, temp_low: 14, precip_prob_day: 0 },
  { period: "Friday", date: "2026-07-10", icon_code: 2, icon_code_night: 33, temp_high: 27, temp_low: 15, precip_prob_day: 30 },
  // Outlook day 8 — wet, amount band, full sentence, feels-like on the day half.
  {
    period: "2026-07-11", date: "2026-07-11", source: "outlook", timesteps_state: "outlook",
    temp_low: 12, temp_high: 22, temp_range: { low: 10, high: 24 },
    pop_day: 55, pop_night: 20, pop_day_display: 55, pop_night_display: null,
    icon_day: 12, icon_night: 30, feels_like_day: 26, feels_like_night: null,
    amount_band: { low: 4, high: 9 },
    sentence: { range_low: 10, range_high: 24, dominant_pop: 55, amount_band: { low: 4, high: 9 } },
  },
  // Outlook day 9 — dry, POP hidden both halves, temperature-only sentence.
  {
    period: "2026-07-12", date: "2026-07-12", source: "outlook", timesteps_state: "outlook",
    temp_low: 13, temp_high: 23, temp_range: { low: 11, high: 25 },
    pop_day: 20, pop_night: 10, pop_day_display: null, pop_night_display: null,
    icon_day: 1, icon_night: 30, feels_like_day: null, feels_like_night: null,
    amount_band: null,
    sentence: { range_low: 11, range_high: 25, dominant_pop: null, amount_band: null },
  },
  // Outlook day 10 — chance band (pop 40, shown), no amount band and no
  // ">= 50" amount line.
  {
    period: "2026-07-13", date: "2026-07-13", source: "outlook", timesteps_state: "outlook",
    temp_low: 14, temp_high: 24, temp_range: { low: 12, high: 26 },
    pop_day: 40, pop_night: 15, pop_day_display: 40, pop_night_display: null,
    icon_day: 2, icon_night: 33, feels_like_day: null, feels_like_night: null,
    amount_band: null,
    sentence: { range_low: 12, range_high: 26, dominant_pop: 40, amount_band: null },
  },
];

const renderExt = () => {
  const card = document.createElement("ec-weather-card");
  card.setConfig({ section: "daily" });
  const hass = buildHass();
  hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: EXT_FORECAST });
  card.hass = hass;
  return card;
};

describe("extended forecast — outlook daily rows", () => {
  it("appends muted outlook rows after the official seven", () => {
    const rows = renderExt().shadowRoot.querySelectorAll(".drow");
    expect(rows).toHaveLength(10);
    // The first 7 are official (no outlook class), the last 3 are outlook.
    for (let i = 0; i < 7; i++) expect(rows[i].classList.contains("drow-outlook")).toBe(false);
    for (let i = 7; i < 10; i++) expect(rows[i].classList.contains("drow-outlook")).toBe(true);
  });

  it("renders no caption between official and outlook rows (removed by user decision)", () => {
    const root = renderExt().shadowRoot;
    expect(root.querySelectorAll(".doutlook-sep")).toHaveLength(0);
    expect(root.innerHTML).not.toContain("Model outlook");
  });

  it("labels outlook rows by weekday derived from the date, not the ISO period", () => {
    const rows = renderExt().shadowRoot.querySelectorAll(".drow");
    // 2026-07-11 is a Saturday.
    expect(rows[7].querySelector(".dday").textContent).toBe("Sat");
    expect(rows[7].querySelector(".dday").textContent).not.toContain("2026");
  });

  it("draws outlook icons from icon_day/icon_night (not icon_code)", () => {
    const rows = renderExt().shadowRoot.querySelectorAll(".drow");
    // icon_day 12 → rainy, icon_night 30 → night.
    const icons = rows[7].querySelectorAll(".dicons ha-icon");
    expect(icons[0].getAttribute("icon")).toBe("mdi:weather-rainy");
    expect(icons[1].getAttribute("icon")).toBe("mdi:weather-night");
  });

  it("shows POP only from *_display (max of the two), no amounts in the row", () => {
    const rows = renderExt().shadowRoot.querySelectorAll(".drow");
    // Day 8: pop_day_display 55, night hidden → 55%.
    expect(rows[7].querySelector(".dprecip").textContent).toContain("55%");
    // No mm/cm amounts in the outlook row even though a band exists.
    expect(rows[7].textContent).not.toContain("mm");
    // Day 9: both displays null → empty precip column.
    expect(rows[8].querySelector(".dprecip").textContent).toBe("");
  });

  it("outlook temps join the same week min/max scale (bars still render)", () => {
    const rows = renderExt().shadowRoot.querySelectorAll(".drow");
    expect(rows[7].querySelector(".dspan")).not.toBeNull();
    expect(rows[7].querySelector(".dhigh").textContent).toBe("22°");
    expect(rows[7].querySelector(".dlow").textContent).toBe("12°");
  });

  it("the section header becomes a dynamic outlook label when outlook rows exist", () => {
    const root = renderExt().shadowRoot;
    expect(root.querySelector(".seclbl").textContent).toBe("10-day");
  });

  it("the official-only header stays '7-day'", () => {
    const root = renderSection("daily");
    expect(root.querySelector(".seclbl").textContent).toBe("7-day");
  });
});

describe("extended forecast — outlook summary popup", () => {
  const popups = () => renderExt()._dailyPopups;

  it("renders a summary view: badge, sentence, day/night boxes, footnote — no timeline", () => {
    const wet = popups()[7].content;
    expect(wet).toContain("ecp-badge");
    expect(wet).toContain("Outlook");
    // Full sentence with pop + amount clause.
    expect(wet).toContain("Likely 10-24°");
    expect(wet).toContain("around 55% chance of rain");
    expect(wet).toContain("4-9 mm possible");
    // Slimmed Day/Night boxes present.
    expect(wet).toContain("ecp-periods");
    // Footnote about model ensembles.
    expect(wet).toContain("model ensembles");
    // No timeline / no placeholder / no chart. (ecp-noh lives in the shared
    // popup CSS, so assert the placeholder ELEMENT is absent, not the class.)
    expect(wet).not.toContain('class="ecp-noh"');
    expect(wet).not.toContain("<svg");
    expect(wet).not.toContain("Timeline");
  });

  it("Day box carries the high median + feels-like; POP always shown", () => {
    const wet = popups()[7].content;
    // Day median high 22°, feels-like 26° (differs → shown).
    expect(wet).toContain("22°");
    expect(wet).toContain("Feels like 26°");
    // Raw per-half POP shown even when the row hid the night POP.
    expect(wet).toContain("55%");
    expect(wet).toContain("20%");
  });

  it("amount band line only appears for a half with pop >= 50", () => {
    const wet = popups()[7].content;
    // Day pop 55 → amount band line; the compact chip form.
    expect(wet).toContain("4-9mm");
  });

  it("dry outlook day → temperature-only sentence, no pop/amount clause", () => {
    const dry = popups()[8].content;
    expect(dry).toContain("Likely 11-25°");
    expect(dry).not.toContain("chance of rain");
    expect(dry).not.toContain("possible");
  });

  it("chance-band outlook day → pop clause but no amount clause", () => {
    const chance = popups()[9].content;
    expect(chance).toContain("around 40% chance of rain");
    expect(chance).not.toContain("possible");
    // pop 40 < 50 → no amount band line even if one existed.
    expect(chance).not.toContain("mm possible");
  });

  it("outlook popup title is the weekday, with a localized date line", () => {
    const wet = popups()[7].content;
    // 2026-07-11 is a Saturday.
    expect(wet).toContain("Saturday");
    expect(wet).toContain("Jul 11");
  });
});

// ── Refinement 1 — skeleton outlook rows on enable ─────────────────────────

// Two official days plus two SKELETON outlook rows (source outlook + pending,
// no temps/icons/sentence) — what the projection emits right after enabling,
// before the outlook fetch lands.
const SKELETON_FORECAST = [
  { period: "Today", date: "2026-07-04", icon_code: 12, icon_code_night: 33, temp_high: 24, temp_low: 17 },
  { period: "Sunday", date: "2026-07-05", icon_code: 0, icon_code_night: 30, temp_high: 29, temp_low: 16 },
  { date: "2026-07-11", source: "outlook", pending: true },  // Saturday
  { date: "2026-07-12", source: "outlook", pending: true },  // Sunday
];

const renderSkeleton = () => {
  const card = document.createElement("ec-weather-card");
  card.setConfig({ section: "daily" });
  const hass = buildHass();
  hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: SKELETON_FORECAST });
  card.hass = hass;
  return card;
};

describe("extended forecast — skeleton outlook rows", () => {
  it("renders skeleton rows muted with a weekday label", () => {
    const rows = renderSkeleton().shadowRoot.querySelectorAll(".drow");
    expect(rows).toHaveLength(4);
    // Both skeletons carry the muted outlook class.
    expect(rows[2].classList.contains("drow-outlook")).toBe(true);
    expect(rows[3].classList.contains("drow-outlook")).toBe(true);
    // Weekday derived from the ISO date (2026-07-11 is a Saturday).
    expect(rows[2].querySelector(".dday").textContent).toBe("Sat");
    expect(rows[2].querySelector(".dday").textContent).not.toContain("2026");
  });

  it("skeleton rows show no icons (not even the missing-icon glyph)", () => {
    const skel = renderSkeleton().shadowRoot.querySelectorAll(".drow")[2];
    // The icon cell exists but is empty — no ha-icon, no missing-icon SVG/glyph.
    expect(skel.querySelectorAll(".dicons ha-icon")).toHaveLength(0);
    expect(skel.querySelector(".dicons").innerHTML.trim()).toBe("");
  });

  it("skeleton rows show no temps, no POP, just the empty bar track", () => {
    const skel = renderSkeleton().shadowRoot.querySelectorAll(".drow")[2];
    expect(skel.querySelector(".dlow").textContent).toBe("");
    expect(skel.querySelector(".dhigh").textContent).toBe("");
    expect(skel.querySelector(".dprecip").textContent).toBe("");
    // Empty range-bar track (no span/dot mark) so the row reads as "loading".
    expect(skel.querySelector(".dbar")).not.toBeNull();
    expect(skel.querySelector(".dspan")).toBeNull();
    expect(skel.querySelector(".ddot")).toBeNull();
  });

  it("skeleton rows have no popup wiring (no popup built for them)", () => {
    const popups = renderSkeleton()._dailyPopups;
    // Real day 0 has a popup; skeleton rows do not.
    expect(popups[0]).toBeTruthy();
    expect(popups[2]).toBeNull();
    expect(popups[3]).toBeNull();
  });
});

// ── Refinement 2 — day-7 overnight-low backfill renders normally ───────────

describe("extended forecast — backfilled last official day", () => {
  it("a last official day whose overnight low was backfilled renders a normal row", () => {
    // merge_weong_into_daily has already filled temp_low from the GEPS trough;
    // the card just renders the row like any other (no card change needed).
    const forecast = [
      { period: "Today", date: "2026-07-04", icon_code: 12, icon_code_night: 33, temp_high: 24, temp_low: 17 },
      // Last official day: high published, low BACKFILLED to 11, night POP 40.
      { period: "Friday", date: "2026-07-10", icon_code: 2, icon_code_night: 33, temp_high: 27, temp_low: 11, precip_prob_night: 40 },
    ];
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast });
    card.hass = hass;
    const rows = card.shadowRoot.querySelectorAll(".drow");
    // The backfilled low renders like any official low; a real range bar spans.
    expect(rows[1].querySelector(".dlow").textContent).toBe("11°");
    expect(rows[1].querySelector(".dhigh").textContent).toBe("27°");
    expect(rows[1].querySelector(".dspan")).not.toBeNull();
    // Not an outlook row — it stays a normal official row (popup built).
    expect(rows[1].classList.contains("drow-outlook")).toBe(false);
    expect(card._dailyPopups[1]).toBeTruthy();
  });
});

describe("extended forecast — GEPS far-day (4-6) popup timeline", () => {
  // A day with 3h GEPS timesteps (amounts null) + precip_windows: the popup
  // timeline shows the window-spanning amount vessels and stepwise POP.
  const GEPS_FORECAST = [
    { period: "Today", date: "2026-07-04", icon_code: 12, icon_code_night: 33, temp_high: 24, temp_low: 17 },
    {
      period: "Thursday", date: "2026-07-09", icon_code: 12, icon_code_night: 33,
      temp_high: 23, temp_low: 15, timesteps_state: "loaded",
      timesteps_day: [
        { time: "2026-07-09T12:00:00Z", temp: 22, icon_code: 12, precipitation_probability: 60, rain_mm: null, snow_cm: null },
        { time: "2026-07-09T15:00:00Z", temp: 23, icon_code: 12, precipitation_probability: 60, rain_mm: null, snow_cm: null },
        { time: "2026-07-09T18:00:00Z", temp: 21, icon_code: 6, precipitation_probability: 50, rain_mm: null, snow_cm: null },
        { time: "2026-07-09T21:00:00Z", temp: 19, icon_code: 30, precipitation_probability: 20, rain_mm: null, snow_cm: null },
      ],
      timesteps_night: [],
      precip_windows: [
        { start: "2026-07-09T12:00:00Z", end: "2026-07-10T00:00:00Z", pop: 60, amount_p25: 4.0, amount_p75: 9.0 },
      ],
    },
  ];

  const gepsPopups = () => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: GEPS_FORECAST });
    card.hass = hass;
    return card._dailyPopups;
  };

  it("renders the spanning amount vessel and the stepwise POP in the popup", () => {
    const content = gepsPopups()[1].content;
    // Spanning window vessel with the amount band label.
    expect(content).toContain("ecs-wfillzone");
    expect(content).toContain("ecs-wvessel");
    expect(content).toContain("4-9mm");
    // Stepwise per-timestep POP still renders in the cluster (60% present).
    expect(content).toContain("60%");
    // The timeline chart is still present (it's a real timeline day).
    expect(content).toContain("<svg");
    // No per-column water-fill vessels (amounts are null on GEPS days).
    // (ecs-fillcol lives in STRIP_CSS, so assert the ELEMENT is absent.)
    expect(content).not.toContain('class="ecs-fillcol"');
  });
});

describe("popup timeline day/night bands (halves mode)", () => {
  // Every non-empty day-label in a strip, in order.
  const bandLabels = (html) =>
    [...html.matchAll(/<div class="ecs-daylbl"[^>]*>([^<]*)<\/div>/g)]
      .map((m) => m[1])
      .filter(Boolean);

  // The popup segments its timeline at the 6/18 boundaries (mirroring the
  // Day/Night boxes) rather than at midnight — so it carries DAY / NIGHT
  // titles, never a calendar date label (user feedback 2026-07-09).
  it("popup timeline renders day/night bands with a DAY title, not a midnight date", () => {
    const card = renderCard("daily");
    const popup = card._dailyPopups[5];
    expect(popup?.content).toBeTruthy();
    expect(popup.content).toContain("ecs-tints");
    expect(popup.content).toContain("ecs-labels");
    // Popup 5's timesteps are both daytime hours → a single DAY segment.
    expect(bandLabels(popup.content)).toEqual(["DAY"]);
    // No calendar date label (e.g. "THU 9") leaks into the strip.
    expect(bandLabels(popup.content).some((label) => /\d/.test(label))).toBe(false);
  });

  it("main hourly section still carries its calendar (weekday + date) labels", () => {
    const root = renderSection("hourly");
    // The card's rolling-days strip keeps the calendar labels unchanged.
    expect(bandLabels(root.innerHTML)).toContain("SAT 4");
  });
});
