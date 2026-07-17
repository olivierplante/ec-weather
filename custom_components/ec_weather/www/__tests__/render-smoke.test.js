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

  it("daily — Tonight with hourly timesteps draws a two-ended bar and both labels", () => {
    // A partial period (high dropped) that carries hourly timesteps: instead of
    // collapsing to a single-point dot, the row derives its range from the
    // hourly temps — spanning bar, both dlow and dhigh labels.
    const forecast = [
      {
        period: "Tonight", date: "2026-07-04", icon_code: null, icon_code_night: 30,
        temp_high: null, temp_low: 16, precip_prob_night: 0,
        timesteps_day: [],
        timesteps_night: [{ temp: 25 }, { temp: 22 }, { temp: 18 }, { temp: 16 }],
      },
      { period: "Sunday", date: "2026-07-05", icon_code: 0, icon_code_night: 30, temp_high: 29, temp_low: 15 },
    ];
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast });
    card.hass = hass;
    const rows = card.shadowRoot.querySelectorAll(".drow");
    const tonight = rows[0];
    // Two-ended span bar (not a single-point dot).
    expect(tonight.querySelector(".dspan")).not.toBeNull();
    expect(tonight.querySelector(".ddot")).toBeNull();
    // Both labels reflect the hourly-derived min/max, not the single low.
    expect(tonight.querySelector(".dlow").textContent).toBe("16°");
    expect(tonight.querySelector(".dhigh").textContent).toBe("25°");
  });

  // Layout regression guard. jsdom can't measure geometry, so this asserts the
  // CSS invariant that keeps every daily row's columns aligned AND keeps the row
  // from overflowing its container. Two historical bugs:
  //   1. `.dday { width: 60px }` — a flex item with default min-width:auto, so
  //      the bold first-row label (fr "Aujourd'hui", ~71px at 600/14px) inflated
  //      the cell while short labels stayed at 60px, misaligning that one row.
  //   2. Fixing (1) by widening the cell to 74px raised the row's hard-minimum
  //      width, so in a tight multi-column layout the extra 14px pushed the
  //      high-temp label past the card's right edge.
  // The cell is now a COMPACT, locked 60px column: flex:0 0 60px sets both the
  // basis and flex-shrink:0 (min-width:auto can't grow it), min-width pins it
  // against deflation, and overflow:hidden is a last-resort guard. Every label
  // we actually render is abbreviated to fit 60px at bold weight (see the
  // dayAbbr test below), so nothing is truncated. Verified against real headless
  // layout: all rows share one dicons/dbar x-offset and .dhigh stays inside the
  // container at 380px and 650px.
  it("daily — label column is a compact, locked, non-inflatable width", () => {
    const style = renderSection("daily").querySelector("style").textContent;
    const ddayRule = style.match(/\.dday\s*\{[^}]*\}/)[0];
    // Locked basis + no shrink (flex:0 0 …) so min-width:auto can't grow it.
    expect(ddayRule).toMatch(/flex:\s*0\s+0\s+60px/);
    // Pinned against deflation too.
    expect(ddayRule).toMatch(/min-width:\s*60px/);
    // Last-resort clip guard against an unexpected EC period name.
    expect(ddayRule).toMatch(/overflow:\s*hidden/);
    // The 74px column that overflowed tight layouts is gone.
    expect(ddayRule).not.toMatch(/74px/);
  });

  // The elastic spines (.dtemps, .dbar) must carry min-width:0 so they can shrink
  // below their content's intrinsic width and absorb the fixed columns — without
  // it a nested flex item refuses to shrink past min-content and the row
  // overflows on the right.
  it("daily — flex spines may shrink (min-width:0 on .dtemps and .dbar)", () => {
    const style = renderSection("daily").querySelector("style").textContent;
    const dtempsRule = style.match(/\.dtemps\s*\{[^}]*\}/)[0];
    const dbarRule = style.match(/\.dbar\s*\{[^}]*\}/)[0];
    expect(dtempsRule).toMatch(/min-width:\s*0/);
    expect(dbarRule).toMatch(/min-width:\s*0/);
  });

  // CSS invariant for the low·bar·high group's breathing room and fit. Two things
  // are pinned:
  //   1. `.dlow` / `.dhigh` are a locked, EQUAL 30px. A bold 15px "-40°" (the
  //      widest realistic value: minus + two digits + degree) measures ~28px in
  //      real Roboto, so the previous 26px overflowed on winter negatives and ate
  //      the card's right-edge padding. 30px fits the worst case with headroom,
  //      and low == high keeps the range bar's two edges aligned down the column.
  //   2. `.dhigh { text-align: right }` pins the high temp's box edge one 8px
  //      row-padding inside the card. That is geometrically symmetric with the
  //      day label — but the value ends in a degree sign, a small, high glyph
  //      whose trailing side-bearing is FONT-SPECIFIC, so the number's visual
  //      mass (the digits) sits further from the card edge than the day letters
  //      sit from the left and the row reads right-heavy. The earlier fix,
  //      `margin-right: -5px`, was a magic number tuned on the harness's Roboto;
  //      the dashboard's Glass theme forces `-apple-system` (San Francisco),
  //      whose degree metrics differ, so the -5px mis-landed in production.
  //      The font-robust replacement splits the value: the digits (`.dhnum`)
  //      stay in flow and right-align to the box edge — pinning the DIGIT mass
  //      one row-padding inside the card, symmetric with the left day label at
  //      ANY font — while the degree (`.ddeg`) is a zero-advance inline-block
  //      that contributes nothing to the line and hangs its glyph into the row
  //      padding. Because the degree carries no advance width, the digit
  //      position no longer depends on the degree's font-specific bearing, and
  //      the row's minimum width (clip onset) drops rather than regressing.
  it("daily — temp boxes are equal-width, fit winter negatives, and the high digit mass is font-robustly right-aligned", () => {
    const style = renderSection("daily").querySelector("style").textContent;
    const dlowRule = style.match(/\.dlow\s*\{[^}]*\}/)[0];
    const dhighRule = style.match(/\.dhigh\s*\{[^}]*\}/)[0];
    const ddegRule = style.match(/\.ddeg\s*\{[^}]*\}/)[0];
    // Both boxes are the same locked 30px (fits bold "-40°" ~28px; keeps the
    // bar edges aligned across every row) — the 26px that clipped negatives is gone.
    expect(dlowRule).toMatch(/width:\s*30px/);
    expect(dhighRule).toMatch(/width:\s*30px/);
    expect(dlowRule).not.toMatch(/width:\s*26px/);
    expect(dhighRule).not.toMatch(/width:\s*26px/);
    // The high's box edge pins to the card-side (symmetric with the day label);
    // the low still hugs the bar. Both are right-aligned but for opposite reasons.
    expect(dhighRule).toMatch(/text-align:\s*right/);
    expect(dlowRule).toMatch(/text-align:\s*right/);
    // The Roboto-tuned magic number is GONE — no font-specific nudge on either box.
    expect(dhighRule).not.toMatch(/margin-right/);
    expect(dlowRule).not.toMatch(/margin-right/);
    // Font-robust trailing-glyph hang: the degree is a zero-advance inline-block
    // so the digits — not the degree's bearing — set the right edge.
    expect(ddegRule).toMatch(/display:\s*inline-block/);
    expect(ddegRule).toMatch(/width:\s*0/);
    // The high value is split into a digit span and a degree span; the low keeps
    // its degree inline (it hugs the bar, so no card-edge symmetry concern).
    const rows = renderSection("daily").querySelectorAll(".drow");
    const highWithValue = [...rows].find((r) => r.querySelector(".dhigh").textContent);
    expect(highWithValue.querySelector(".dhigh .dhnum")).not.toBeNull();
    expect(highWithValue.querySelector(".dhigh .ddeg")).not.toBeNull();
    expect(highWithValue.querySelector(".dhigh .ddeg").textContent).toBe("°");
    // textContent is unchanged for consumers (still e.g. "29°").
    expect(highWithValue.querySelector(".dhigh").textContent).toMatch(/^-?\d+°$/);
  });

  // The wider temp boxes cost the row 8px of hard-minimum width; the narrow
  // container query pays it back by tightening the low·bar·high gaps (12px -> 8px,
  // two gaps = 8px) so the clip onset does not regress. The bar's 58px narrow
  // floor and the untouched outer row padding must both survive that block.
  it("daily — narrow mode reclaims temp-box width via tighter gaps, keeps the bar floor", () => {
    const style = renderSection("daily").querySelector("style").textContent;
    const narrow = style.match(/@container\s*\(max-width:\s*430px\)\s*\{[\s\S]*?\n\s*\}\s*\n/)[0];
    // Base gap stays 12px on wide; narrow overrides .dtemps to 8px.
    expect(style.match(/\.dtemps\s*\{[^}]*\}/)[0]).toMatch(/gap:\s*12px/);
    expect(narrow).toMatch(/\.dtemps\s*\{[^}]*gap:\s*8px[^}]*\}/);
    // The bar's narrow floor is preserved.
    expect(narrow).toMatch(/\.dbar\s*\{[^}]*min-width:\s*58px[^}]*\}/);
  });

  // A single dashboard column can be far tighter than the 430px narrow tier
  // assumes: the measured worst-case daily host is 238.5px (a 288.5px ha-card
  // with 24px card_mod padding each side). At the 430px tier the row's
  // hard-minimum (~254px) overflows that host by ~16px (up to ~35px on winter
  // negatives), pushing the high-temp box past the card's right edge — the
  // long-standing "not centered" defect. An ultra-narrow tier (engages at host
  // <= 300px) reclaims the deficit WITHOUT touching the outer row padding (the
  // visible margin): it tightens the row and low·bar·high gaps to 4px, trims the
  // label column 60px -> 54px (bold "Tonight" ~51px in Roboto still clears it
  // with headroom) and the icon cell 44px -> 37px with 16px icons, pins the 30px
  // temp boxes with flex-shrink:0 (bar edges stay aligned; negatives can't widen
  // the row), and drops the bar's floor to 16px so the bar is the sole
  // shrink-sink. All told the reclaimed slack goes to the range bar (34.5px ->
  // 69.5px at the 238.5px host, once the 6px vertical / 1px horizontal row
  // padding lands too). overflow-x:clip on the row is the
  // belt-and-braces backstop for pathological narrow widths no real layout
  // produces.
  it("daily — ultra-narrow tier fits the 238.5px host with symmetric margins", () => {
    const style = renderSection("daily").querySelector("style").textContent;
    const ultra = style.match(/@container\s*\(max-width:\s*300px\)\s*\{[\s\S]*?\n\s*\}\s*\n/)[0];
    // Breakpoint is the ultra tier, distinct from and below the 430px narrow tier.
    expect(style).toMatch(/@container\s*\(max-width:\s*300px\)/);
    // Row + low·bar·high gaps tighten to 4px (base row gap stays 12px on wide).
    // These 4px gaps, plus the trimmed label/icon columns and the 6px vertical /
    // 1px horizontal row padding below, hand the reclaimed slack to the range
    // bar (34.5px -> 69.5px at the 238.5px host).
    expect(style.match(/\.drow\s*\{[^}]*\}/)[0]).toMatch(/gap:\s*12px/);
    expect(ultra).toMatch(/\.drow\s*\{[^}]*gap:\s*4px[^}]*\}/);
    expect(ultra).toMatch(/\.dtemps\s*\{[^}]*gap:\s*4px[^}]*\}/);
    // The label column drops 60px -> 54px: the widest BOLD label ("Tonight",
    // ~51px in Roboto) still clears it with >=2px headroom; overflow:hidden on
    // the base .dday backstops any unexpected wider EC period word.
    expect(ultra).toMatch(/\.dday\s*\{[^}]*flex:\s*0\s+0\s+54px[^}]*\}/);
    expect(ultra).toMatch(/\.dday\s*\{[^}]*min-width:\s*54px[^}]*\}/);
    // The icon cell drops 44px -> 37px with the daily icons shrunk 18px -> 16px
    // (two 16px SVGs + their 3px gap = 35px, centered in 37px). The size override
    // needs !important because each row's icon size is set inline in the markup.
    expect(ultra).toMatch(/\.dicons\s*\{[^}]*width:\s*37px[^}]*\}/);
    expect(ultra).toMatch(/\.dicons\s+ha-icon\s*\{[^}]*--mdc-icon-size:\s*16px\s*!important[^}]*\}/);
    // Temp boxes are pinned: flex-shrink:0 keeps them a locked 30px so the range
    // bar's two edges stay column-aligned and negatives can't widen the row.
    expect(ultra).toMatch(/\.dlow,\s*\.dhigh\s*\{[^}]*flex-shrink:\s*0[^}]*\}/);
    // The bar is the sole shrink-sink here: its 58px narrow floor drops to 16px.
    expect(ultra).toMatch(/\.dbar\s*\{[^}]*min-width:\s*16px[^}]*\}/);
    // Belt-and-braces guard: the row never paints outside the host even below
    // the tier's fitting minimum. overflow-x (not overflow) keeps the vertical
    // axis visible so the POP/amount float labels above the bar are never cut.
    expect(ultra).toMatch(/\.drow\s*\{[^}]*overflow-x:\s*clip[^}]*\}/);
    expect(ultra).not.toMatch(/\.drow\s*\{[^}]*overflow:\s*hidden[^}]*\}/);
    // Row padding: vertical stays 6px (row rhythm), HORIZONTAL drops to 1px so
    // the row content shares ONE left rail with the section title above it. The
    // title (.seclbl) has no horizontal padding, so its ink sits at the daily
    // host's content edge; the row's day label previously sat one 6px row-pad
    // further in, so the title read ~5.4px LEFT of the day letters at the 238.5px
    // host (two competing rails the user saw as a mis-alignment). At 1px the
    // day-label ink lands ~0.4px right of the title ink (bold "Tonight"), within
    // a pixel — a single rail. Mirrored 1px on the right keeps the high-temp digit
    // ink at the same right-inset, so the row stays L/R symmetric. The ~10px freed
    // across both sides flows to the range bar (the sole shrink-sink): 59.5px ->
    // 69.5px at the 238.5px host. The base .drow keeps 8px on the wider tiers.
    expect(style.match(/\.drow\s*\{[^}]*\}/)[0]).toMatch(/padding:\s*8px/);
    expect(ultra).toMatch(/\.drow\s*\{[^}]*padding:\s*6px\s+1px[^}]*\}/);
    // Mixed winter precip (POP + rain mm + snow cm) is the float's worst case:
    // three values above the bar. The float centres over the bar, so content
    // wider than the bar's clear span reaches over the flanking temp boxes — the
    // low temp, right-aligned toward the bar, is what it crowds. This tier shrinks
    // the float to fit that span: font 10px -> 9px, inter-value gap 7px -> 2px.
    // The gap was 4px until the model-estimate "~" prefix widened the group; 2px
    // reclaims the tilde's width so "90% ~12mm 8cm" fits the 77.5px clear span at
    // the 238.5px host. Font stays 9px (legibility); all three values stay visible.
    expect(style.match(/\.dfloat\s*\{[^}]*\}/)[0]).toMatch(/font-size:\s*10px/);
    expect(ultra).toMatch(/\.dfloat\s*\{[^}]*font-size:\s*9px[^}]*\}/);
    expect(ultra).toMatch(/\.dfloat\s*\{[^}]*gap:\s*2px[^}]*\}/);
    // Source order: the ultra tier must follow the 430px tier so its tighter
    // values win the cascade at widths where both queries match.
    expect(style.indexOf("max-width: 300px")).toBeGreaterThan(style.indexOf("max-width: 430px"));
  });

  // The label is `dayAbbr[firstWord] || firstWord`, so any first-row period word
  // wider than the 60px column must have a dayAbbr entry or it would be clipped.
  // French "Aujourd'hui" (~71px bold) is the one that overflows; it abbreviates
  // to the established shorthand "Ajd". English "Today"/"Tonight" and the French
  // tonight period ("Ce soir…" → "Ce") already fit 60px unabbreviated.
  it("daily — first-row period words are abbreviated to fit the compact column", () => {
    const renderFirstLabel = (language, period) => {
      const card = document.createElement("ec-weather-card");
      card.setConfig({ section: "daily" });
      const hass = buildHass();
      hass.language = language;
      hass.states["sensor.ec_daily_forecast"] = state("ok", {
        forecast: [{ ...DAILY_FORECAST[0], period }, ...DAILY_FORECAST.slice(1)],
      });
      card.hass = hass;
      return card.shadowRoot.querySelector(".drow .dday").textContent;
    };
    // The regression: "Aujourd'hui" must not render in full (it overflows 60px).
    expect(renderFirstLabel("fr", "Aujourd'hui")).toBe("Ajd");
    // These already fit; they are kept intact.
    expect(renderFirstLabel("en", "Today")).toBe("Today");
    expect(renderFirstLabel("en", "Tonight")).toBe("Tonight");
    expect(renderFirstLabel("fr", "Ce soir et cette nuit")).toBe("Ce");
  });
});

describe("precip source indicator — model estimates get a leading '~', EC-stated amounts render as-is", () => {
  const renderDailyRows = (forecast) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast });
    card.hass = hass;
    return card.shadowRoot.querySelectorAll(".drow");
  };
  const renderTodayPanel = (entry0) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "current" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: [entry0] });
    card.hass = hass;
    return card.shadowRoot.querySelector(".ppanel").textContent;
  };

  it("daily column: EC-stated accumulation renders bare (byte-identical, no tilde)", () => {
    const rows = renderDailyRows([
      { period: "Today", date: "2026-07-06", icon_code: 12, temp_high: 22, temp_low: 14,
        precip_prob_day: 70, precip_accum_amount: 8, precip_accum_unit: "mm" },
    ]);
    const col = rows[0].querySelector(".dprecip").textContent;
    const float = rows[0].querySelector(".dfloat").textContent;
    expect(col).toContain("8mm");
    expect(col).not.toContain("~");
    expect(float).toContain("8mm");
    expect(float).not.toContain("~");
  });

  it("daily column: model-derived amount gets a leading tilde in both column and float", () => {
    const rows = renderDailyRows([
      { period: "Today", date: "2026-07-06", icon_code: 12, temp_high: 22, temp_low: 14,
        precip_prob_day: 70, rain_mm_day: 8 },
    ]);
    expect(rows[0].querySelector(".dprecip").textContent).toContain("~8mm");
    expect(rows[0].querySelector(".dfloat").textContent).toContain("~8mm");
  });

  it("daily column: mixed model rain+snow — one tilde leads the group, snow bare, POP untouched", () => {
    const rows = renderDailyRows([
      { period: "Today", date: "2026-07-06", icon_code: 12, temp_high: 22, temp_low: 14,
        precip_prob_day: 90, rain_mm_day: 12, snow_cm_day: 8 },
    ]);
    const col = rows[0].querySelector(".dprecip").textContent;
    expect(col).toContain("~12mm");
    expect(col).toContain("8cm");
    expect(col).not.toContain("~8cm");
    // POP is never tilded.
    expect(col).toContain("90%");
    expect(col).not.toContain("~90");
    // Exactly one tilde across the whole precip group.
    expect((col.match(/~/g) || []).length).toBe(1);
    // The float above the bar carries the same single-tilde group.
    const float = rows[0].querySelector(".dfloat").textContent;
    expect((float.match(/~/g) || []).length).toBe(1);
    expect(float).toContain("~12mm");
    expect(float).toContain("8cm");
  });

  it("daily column: snow-only model estimate tildes the snow (the sole amount)", () => {
    const rows = renderDailyRows([
      { period: "Today", date: "2026-07-06", icon_code: 12, temp_high: 22, temp_low: 14,
        precip_prob_day: 80, snow_cm_day: 6 },
    ]);
    expect(rows[0].querySelector(".dprecip").textContent).toContain("~6cm");
  });

  it("today panel: model estimate tilded, EC-stated bare, POP never tilded", () => {
    const ec = renderTodayPanel({ period: "Today", date: "2026-07-04", precip_prob_day: 70,
      precip_accum_amount: 8, precip_accum_unit: "mm" });
    expect(ec).toContain("8mm");
    expect(ec).not.toContain("~");

    const model = renderTodayPanel({ period: "Today", date: "2026-07-04", precip_prob_day: 70, rain_mm_day: 8 });
    expect(model).toContain("~8mm");
    expect(model).not.toContain("~70");
  });

  it("today panel: mixed model rain+snow tildes only the leading amount", () => {
    const panel = renderTodayPanel({ period: "Today", date: "2026-07-04", precip_prob_day: 90,
      rain_mm_day: 12, snow_cm_day: 8 });
    expect(panel).toContain("~12mm");
    expect(panel).toContain("8cm");
    expect(panel).not.toContain("~8cm");
    expect((panel.match(/~/g) || []).length).toBe(1);
  });
});

describe("precip amount labels — byte-identity across sites (only the popup gains a tilde)", () => {
  // The tilde convention + mm/cm formatting were consolidated into one helper
  // (precipAmtLabels). Every pre-existing render site must emit byte-identical
  // label text; these pin the exact strings so the consolidation can't drift.
  const renderRootDaily = (forecast) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast });
    card.hass = hass;
    return card.shadowRoot;
  };
  const renderRootCurrent = (entry0) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "current" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: [entry0] });
    card.hass = hass;
    return card.shadowRoot;
  };
  const dailyBase = (extra) => ({
    period: "Today", date: "2026-07-06", icon_code: 12, temp_high: 22, temp_low: 14, ...extra,
  });

  it("daily column .damts + .dfloat: EC-stated 8mm is exactly '8mm' / '70%8mm'", () => {
    const row = renderRootDaily([dailyBase({ precip_prob_day: 70, precip_accum_amount: 8, precip_accum_unit: "mm" })])
      .querySelector(".drow");
    expect(row.querySelector(".damts").textContent).toBe("8mm");
    expect(row.querySelector(".dfloat").textContent).toBe("70%8mm");
  });

  it("daily column .damts + .dfloat: model estimate 8mm is exactly '~8mm' / '70%~8mm'", () => {
    const row = renderRootDaily([dailyBase({ precip_prob_day: 70, rain_mm_day: 8 })]).querySelector(".drow");
    expect(row.querySelector(".damts").textContent).toBe("~8mm");
    expect(row.querySelector(".dfloat").textContent).toBe("70%~8mm");
  });

  it("daily column .damts + .dfloat: mixed model estimate is exactly '~12mm8cm' / '90%~12mm8cm'", () => {
    const row = renderRootDaily([dailyBase({ precip_prob_day: 90, rain_mm_day: 12, snow_cm_day: 8 })]).querySelector(".drow");
    expect(row.querySelector(".damts").textContent).toBe("~12mm8cm");
    expect(row.querySelector(".dfloat").textContent).toBe("90%~12mm8cm");
  });

  it("today panel .pchips: EC-stated is bare '8mm', model estimate is '~8mm'", () => {
    const ec = renderRootCurrent({ period: "Today", date: "2026-07-04", precip_prob_day: 70,
      precip_accum_amount: 8, precip_accum_unit: "mm" });
    expect(ec.querySelector(".prow .pchips").textContent).toBe("8mm");

    const model = renderRootCurrent({ period: "Today", date: "2026-07-04", precip_prob_day: 70, rain_mm_day: 8 });
    expect(model.querySelector(".prow .pchips").textContent).toBe("~8mm");
  });

  it("today panel .pchips: mixed model estimate is exactly '~12mm8cm'", () => {
    const panel = renderRootCurrent({ period: "Today", date: "2026-07-04", precip_prob_day: 90,
      rain_mm_day: 12, snow_cm_day: 8 });
    expect(panel.querySelector(".prow .pchips").textContent).toBe("~12mm8cm");
  });
});

describe("popup day/night boxes — model per-half amounts always wear the '~'", () => {
  // The popup's Day/Night box amounts read the raw per-half model fields
  // (rain_mm_day/night, snow_cm_day/night), present only under the beta estimate
  // option — so they are unconditionally estimates and always get the tilde.
  const renderPopupContent = (entry) => {
    const card = document.createElement("ec-weather-card");
    card.setConfig({ section: "daily" });
    const hass = buildHass();
    hass.states["sensor.ec_daily_forecast"] = state("ok", { forecast: [entry] });
    card.hass = hass;
    return card._dailyPopups[0].content;
  };
  const parse = (content) => {
    const div = document.createElement("div");
    div.innerHTML = content;
    return div;
  };
  const dayEntry = (extra) => ({
    period: "Monday", date: "2026-07-06", icon_code: 12, icon_code_night: 30,
    temp_high: 22, temp_low: 14, ...extra,
  });

  it("day box, rain only: the rain line reads '~8mm'", () => {
    const div = parse(renderPopupContent(dayEntry({ precip_prob_day: 70, rain_mm_day: 8 })));
    expect(div.querySelector(".ecp-rain").textContent).toBe("~8mm");
    expect(div.querySelector(".ecp-snow")).toBeNull();
  });

  it("night box, rain only: the night rain line reads '~3mm'", () => {
    const div = parse(renderPopupContent(dayEntry({ precip_prob_night: 60, rain_mm_night: 3 })));
    expect(div.querySelector(".ecp-rain").textContent).toBe("~3mm");
  });

  it("day box, snow only: the snow line reads '~6cm'", () => {
    const div = parse(renderPopupContent(dayEntry({ precip_prob_day: 80, snow_cm_day: 6 })));
    expect(div.querySelector(".ecp-snow").textContent).toBe("~6cm");
    expect(div.querySelector(".ecp-rain")).toBeNull();
  });

  it("day box, rain + snow: ONE tilde leads (rain '~12mm'), snow bare ('8cm')", () => {
    const div = parse(renderPopupContent(dayEntry({ precip_prob_day: 90, rain_mm_day: 12, snow_cm_day: 8 })));
    expect(div.querySelector(".ecp-rain").textContent).toBe("~12mm");
    expect(div.querySelector(".ecp-snow").textContent).toBe("8cm");
  });

  it("day and night boxes each wear their own tilde", () => {
    const div = parse(renderPopupContent(dayEntry({
      precip_prob_day: 70, rain_mm_day: 8, precip_prob_night: 60, rain_mm_night: 3 })));
    const rains = div.querySelectorAll(".ecp-rain");
    expect(rains.length).toBe(2);
    expect(rains[0].textContent).toBe("~8mm");
    expect(rains[1].textContent).toBe("~3mm");
  });

  it("no amounts: neither box emits a rain/snow line (unchanged)", () => {
    const div = parse(renderPopupContent(dayEntry({ precip_prob_day: 40 })));
    expect(div.querySelector(".ecp-rain")).toBeNull();
    expect(div.querySelector(".ecp-snow")).toBeNull();
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
