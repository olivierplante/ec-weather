/**
 * Phase D — extended forecast rendering (card side).
 *
 * Pure helpers behind the far-days rendering:
 *   - fmtAmtBand     compact "4-9mm" band label (single value when low==high)
 *   - tf             {placeholder} interpolation over an I18N template
 *   - spanningWindows  column math for the window-spanning amount vessels
 *
 * Plus the buildHourlyStripHtml integration: a geps day (per-timestep amounts
 * always null) carrying precip_windows renders ONE wide water-fill block per
 * 12h window with pop >= 30, and — critically — the strip output for days 0-3
 * (no precip_windows) stays byte-identical to today.
 */

import { describe, expect, it } from "vitest";

import {
  buildHourlyStripHtml,
  fmtAmtBand,
  spanningWindows,
  tf,
} from "../ec-weather-card.js";

const hass24 = { language: "en", locale: { time_format: "24" } };

// A geps day at 3h cadence: amounts ALWAYS null (window-spanning vessels carry
// the amount instead). Times UTC so the window comparison is unambiguous.
const GEPS_SERIES = [
  { time: "2026-07-16T12:00:00Z", temp: 22, icon_code: 12, precipitation_probability: 60, rain_mm: null, snow_cm: null },
  { time: "2026-07-16T15:00:00Z", temp: 23, icon_code: 12, precipitation_probability: 60, rain_mm: null, snow_cm: null },
  { time: "2026-07-16T18:00:00Z", temp: 21, icon_code: 6, precipitation_probability: 50, rain_mm: null, snow_cm: null },
  { time: "2026-07-16T21:00:00Z", temp: 19, icon_code: 30, precipitation_probability: 20, rain_mm: null, snow_cm: null },
];

const DAY_WINDOW = {
  start: "2026-07-16T12:00:00Z", end: "2026-07-17T00:00:00Z",
  pop: 60, amount_p25: 4.0, amount_p75: 9.0,
};
const DRY_NIGHT_WINDOW = {
  start: "2026-07-17T00:00:00Z", end: "2026-07-17T12:00:00Z",
  pop: 10, amount_p25: null, amount_p75: null,
};

describe("fmtAmtBand — compact amount band label", () => {
  it("low != high → 'lo-hiUNIT'", () => {
    expect(fmtAmtBand(4, 9, "mm")).toBe("4-9mm");
  });

  it("low == high → single value", () => {
    expect(fmtAmtBand(5, 5, "mm")).toBe("5mm");
  });

  it("missing high → single value", () => {
    expect(fmtAmtBand(6, null, "mm")).toBe("6mm");
  });

  it("missing low → single (the high) value", () => {
    expect(fmtAmtBand(null, 7, "mm")).toBe("7mm");
  });

  it("both absent → null", () => {
    expect(fmtAmtBand(null, null, "mm")).toBeNull();
    expect(fmtAmtBand(0, 0, "mm")).toBeNull();
  });

  it("sub-1 amounts read '<1'", () => {
    expect(fmtAmtBand(0.4, 0.8, "mm")).toBe("<1mm");
  });

  it("prose unit with a leading space is preserved (sentence use)", () => {
    expect(fmtAmtBand(4, 9, " mm")).toBe("4-9 mm");
  });
});

describe("tf — template interpolation", () => {
  it("substitutes named placeholders", () => {
    const hass = { language: "en" };
    // outlookTemp: "Likely {low}-{high}°"
    expect(tf(hass, "outlookTemp", { low: 11, high: 27 })).toBe("Likely 11-27°");
  });

  it("leaves an unknown placeholder untouched", () => {
    const hass = { language: "en" };
    expect(tf(hass, "outlookPop", { nope: 1 })).toContain("{pop}");
  });
});

describe("spanningWindows — column math for the amount vessels", () => {
  it("a window covering every column spans the full width", () => {
    const spans = spanningWindows(GEPS_SERIES, [DAY_WINDOW], 60);
    expect(spans).toHaveLength(1);
    expect(spans[0].firstIdx).toBe(0);
    expect(spans[0].lastIdx).toBe(3);
    expect(spans[0].left).toBe(0);
    expect(spans[0].width).toBe(4 * 60);
    expect(spans[0].amountLow).toBe(4.0);
    expect(spans[0].amountHigh).toBe(9.0);
  });

  it("a window covering only the first two columns is placed on them", () => {
    const half = { ...DAY_WINDOW, end: "2026-07-16T18:00:00Z" };
    const spans = spanningWindows(GEPS_SERIES, [half], 60);
    expect(spans[0].firstIdx).toBe(0);
    expect(spans[0].lastIdx).toBe(1);
    expect(spans[0].left).toBe(0);
    expect(spans[0].width).toBe(2 * 60);
  });

  it("a window offset into the middle places left at its first column", () => {
    const mid = {
      start: "2026-07-16T18:00:00Z", end: "2026-07-17T00:00:00Z",
      pop: 55, amount_p25: 2, amount_p75: 5,
    };
    const spans = spanningWindows(GEPS_SERIES, [mid], 60);
    expect(spans[0].firstIdx).toBe(2);
    expect(spans[0].left).toBe(2 * 60);
    expect(spans[0].width).toBe(2 * 60);
  });

  it("pop < 30 renders nothing", () => {
    expect(spanningWindows(GEPS_SERIES, [DRY_NIGHT_WINDOW], 60)).toHaveLength(0);
    const lowPop = { ...DAY_WINDOW, pop: 25 };
    expect(spanningWindows(GEPS_SERIES, [lowPop], 60)).toHaveLength(0);
  });

  it("a window with pop >= 30 but no band data renders nothing", () => {
    const noBand = { ...DAY_WINDOW, amount_p25: null, amount_p75: null };
    expect(spanningWindows(GEPS_SERIES, [noBand], 60)).toHaveLength(0);
  });

  it("a window that matches no rendered column is skipped", () => {
    const offscreen = {
      start: "2026-07-20T12:00:00Z", end: "2026-07-21T00:00:00Z",
      pop: 60, amount_p25: 4, amount_p75: 9,
    };
    expect(spanningWindows(GEPS_SERIES, [offscreen], 60)).toHaveLength(0);
  });

  it("only qualifying windows survive when several are supplied", () => {
    const spans = spanningWindows(GEPS_SERIES, [DAY_WINDOW, DRY_NIGHT_WINDOW], 60);
    expect(spans).toHaveLength(1);
    expect(spans[0].pop).toBe(60);
  });
});

describe("buildHourlyStripHtml — window-spanning amount vessels (days 4-6)", () => {
  it("renders one wide vessel per qualifying window with the band label", () => {
    const html = buildHourlyStripHtml(GEPS_SERIES, hass24, {
      showDayBands: false, precipWindows: [DAY_WINDOW, DRY_NIGHT_WINDOW],
    });
    expect(html).toContain("ecs-wfillzone");
    // Exactly one spanning vessel (the dry night window renders nothing).
    expect((html.match(/ecs-wvessel/g) || []).length).toBe(1);
    // The amount band rides the shared compact label style.
    expect(html).toContain("4-9mm");
    expect(html).toContain("ecs-rainamt");
    // A wide filled block (rain color rides the .ecs-wblock class, so it's in
    // STRIP_CSS, not inlined here).
    expect(html).toContain("ecs-wblock");
  });

  it("does not emit per-column vessels for a geps day (amounts are null)", () => {
    const html = buildHourlyStripHtml(GEPS_SERIES, hass24, {
      showDayBands: false, precipWindows: [DAY_WINDOW],
    });
    expect(html).not.toContain("ecs-fillcol");
    expect(html).not.toContain('class="ecs-vessel"');
  });

  it("a band with equal p25/p75 shows a single value", () => {
    const flat = { ...DAY_WINDOW, amount_p25: 5, amount_p75: 5 };
    const html = buildHourlyStripHtml(GEPS_SERIES, hass24, {
      showDayBands: false, precipWindows: [flat],
    });
    expect(html).toContain("5mm");
    expect(html).not.toContain("5-5");
  });

  it("no qualifying window → no fill zone at all", () => {
    const html = buildHourlyStripHtml(GEPS_SERIES, hass24, {
      showDayBands: false, precipWindows: [DRY_NIGHT_WINDOW],
    });
    expect(html).not.toContain("ecs-wfillzone");
    expect(html).not.toContain("ecs-fill");
  });
});

describe("buildHourlyStripHtml — days 0-3 regression guard (no precip_windows)", () => {
  // A day-0..3 style window: real per-hour amounts, no precip_windows.
  const WET_HOURLY = [
    { time: "2026-07-04T09:00:00", temp: 5, icon_code: 1, precipitation_probability: 40, rain_mm: 1, snow_cm: 0 },
    { time: "2026-07-04T10:00:00", temp: 6, icon_code: 6, precipitation_probability: 60, rain_mm: 2, snow_cm: 0 },
  ];

  it("output is identical whether the option is absent, null or an empty array", () => {
    const base = buildHourlyStripHtml(WET_HOURLY, hass24, { showDayBands: false });
    const nullOpt = buildHourlyStripHtml(WET_HOURLY, hass24, { showDayBands: false, precipWindows: null });
    const emptyOpt = buildHourlyStripHtml(WET_HOURLY, hass24, { showDayBands: false, precipWindows: [] });
    expect(nullOpt).toBe(base);
    expect(emptyOpt).toBe(base);
  });

  it("still renders the original per-column water-fill vessels, never the window ones", () => {
    const html = buildHourlyStripHtml(WET_HOURLY, hass24, { showDayBands: false });
    expect(html).toContain('class="ecs-vessel"');
    expect(html).toContain("ecs-fillcol");
    expect(html).not.toContain("ecs-wfillzone");
    expect(html).not.toContain("ecs-wvessel");
  });

  it("the full card-default strip (day bands) is byte-identical to the empty-window path", () => {
    const base = buildHourlyStripHtml(WET_HOURLY, hass24, {});
    const emptyOpt = buildHourlyStripHtml(WET_HOURLY, hass24, { precipWindows: [] });
    expect(emptyOpt).toBe(base);
  });
});
