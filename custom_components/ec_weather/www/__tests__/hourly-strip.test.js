/**
 * The shared hourly-strip builder — the single source of truth behind both the
 * card's multi-day hourly section and the popup's single-day timeline. These
 * pin the option matrix (day bands, the compact size modifier), the column
 * order (time+icon header → curve → temp/FL/POP cluster → water-fill zone),
 * the always-reserved FL/POP lines, and the accumulation water-fill rules.
 *
 * Times use zone-less ISO strings ("...T00:00:00", no Z/offset) so `new Date`
 * parses them as local time — getHours() is then deterministic across CI TZs.
 */

import { describe, expect, it } from "vitest";

import { buildHourlyStripHtml, fmtHourLabel, tempColor } from "../ec-weather-card.js";

// The stroke gradient lives in its own <linearGradient id="ecs-curve-stroke">;
// slice it out so stop counts don't collide with the area-fill gradient's stops.
const strokeGradient = (html) => {
  const start = html.indexOf('id="ecs-curve-stroke"');
  if (start === -1) return "";
  return html.slice(start, html.indexOf("</linearGradient>", start));
};
const step = (hour) => `2026-01-07T${String(hour).padStart(2, "0")}:00:00`;
const seriesOf = (temps) =>
  temps.map((temp, i) => ({ time: step(9 + i), temp, icon_code: 1 }));

const hass24 = { language: "en", locale: { time_format: "24" } };
const hass12 = { language: "en", locale: { time_format: "12" } };

describe("fmtHourLabel", () => {
  it("24h clock zero-pads and uses HH:00", () => {
    expect(fmtHourLabel(new Date(2026, 0, 1, 0), true)).toBe("00:00");
    expect(fmtHourLabel(new Date(2026, 0, 1, 9), true)).toBe("09:00");
    expect(fmtHourLabel(new Date(2026, 0, 1, 12), true)).toBe("12:00");
    expect(fmtHourLabel(new Date(2026, 0, 1, 15), true)).toBe("15:00");
  });

  it("12h clock names midnight and noon, AM/PM otherwise", () => {
    expect(fmtHourLabel(new Date(2026, 0, 1, 0), false)).toBe("12 AM");
    expect(fmtHourLabel(new Date(2026, 0, 1, 12), false)).toBe("12 PM");
    expect(fmtHourLabel(new Date(2026, 0, 1, 9), false)).toBe("9 AM");
    expect(fmtHourLabel(new Date(2026, 0, 1, 15), false)).toBe("3 PM");
  });
});

// A window spanning a midnight boundary: 22:00, 23:00, 00:00(next), 01:00.
const CROSS_MIDNIGHT = [
  { time: "2026-01-07T22:00:00", temp: 5, icon_code: 1, feels_like: 3, precipitation_probability: 0 },
  { time: "2026-01-07T23:00:00", temp: 4, icon_code: 1, feels_like: 2, precipitation_probability: 0 },
  { time: "2026-01-08T00:00:00", temp: 3, icon_code: 1, feels_like: 1, precipitation_probability: 0 },
  { time: "2026-01-08T01:00:00", temp: 2, icon_code: 1, feels_like: 0, precipitation_probability: 0 },
];

describe("buildHourlyStripHtml — day bands", () => {
  it("renders tints + midnight labels when showDayBands (card default)", () => {
    const html = buildHourlyStripHtml(CROSS_MIDNIGHT, hass24, {});
    expect(html).toContain("ecs-tints");
    expect(html).toContain("ecs-labels");
    expect(html).toContain("ecs-daylbl");
    // Label at index 0 (WED 7) and at the midnight crossing (THU 8).
    expect(html).toContain("WED 7");
    expect(html).toContain("THU 8");
    // Second calendar day gets the alternating tint.
    expect(html).toContain("var(--ecw-tint)");
  });

  it("omits bands and labels when showDayBands is false (popup)", () => {
    const html = buildHourlyStripHtml(CROSS_MIDNIGHT, hass24, { showDayBands: false });
    expect(html).not.toContain("ecs-tints");
    expect(html).not.toContain("ecs-labels");
    expect(html).not.toContain("ecs-daylbl");
  });

  it("places the tint belt inside the padded chart band, below the label row", () => {
    const html = buildHourlyStripHtml(CROSS_MIDNIGHT, hass24, {});
    const labelsAt = html.indexOf("ecs-labels");
    const bandAt = html.indexOf("ecs-band");
    const tintsAt = html.indexOf("ecs-tints");
    expect(labelsAt).toBeLessThan(bandAt);
    expect(bandAt).toBeLessThan(tintsAt);
  });
});

describe("buildHourlyStripHtml — column order (header top, cluster below curve)", () => {
  const one = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, feels_like: 9, precipitation_probability: 30 }];

  it("time + icon form the header above the chart; temp/FL/POP cluster sits below", () => {
    const html = buildHourlyStripHtml(one, hass24, { showDayBands: false });
    const timeAt = html.indexOf("ecs-time");
    const iconAt = html.indexOf("ecs-icon");
    const svgAt = html.indexOf("<svg");
    const clusterAt = html.indexOf("ecs-cluster");
    const tempAt = html.indexOf("ecs-temp");
    const flAt = html.indexOf("ecs-fl");
    const popAt = html.indexOf("ecs-pop");
    expect(timeAt).toBeLessThan(iconAt);
    expect(iconAt).toBeLessThan(svgAt);
    expect(svgAt).toBeLessThan(clusterAt);
    expect(clusterAt).toBeLessThan(tempAt);
    expect(tempAt).toBeLessThan(flAt);
    expect(flAt).toBeLessThan(popAt);
  });

  it("keeps the same header-top order in the compact (popup) preset", () => {
    const html = buildHourlyStripHtml(one, hass24, { showDayBands: false, compact: true });
    const timeAt = html.indexOf("ecs-time");
    const iconAt = html.indexOf("ecs-icon");
    const svgAt = html.indexOf("<svg");
    expect(timeAt).toBeLessThan(iconAt);
    expect(iconAt).toBeLessThan(svgAt);
  });
});

describe("buildHourlyStripHtml — reserved FL/POP cluster lines", () => {
  it("FL and POP lines always render, blank (&nbsp;) when absent", () => {
    const noExtras = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1 }];
    const html = buildHourlyStripHtml(noExtras, hass24, { showDayBands: false });
    expect(html).toContain('<div class="ecs-fl">&nbsp;</div>');
    expect(html).toContain('<div class="ecs-pop">&nbsp;</div>');
  });

  it("POP 0 renders a reserved blank line, not 0%", () => {
    const zeroPop = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, precipitation_probability: 0 }];
    const html = buildHourlyStripHtml(zeroPop, hass24, { showDayBands: false });
    expect(html).toContain('<div class="ecs-pop">&nbsp;</div>');
    expect(html).not.toContain("0%");
  });

  it("FL equal to the temp is blanked (reads as a modifier only when it differs)", () => {
    const equal = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, feels_like: 5 }];
    const html = buildHourlyStripHtml(equal, hass24, { showDayBands: false });
    expect(html).toContain('<div class="ecs-fl">&nbsp;</div>');
    expect(html).not.toContain("FL 5°");
  });
});

describe("buildHourlyStripHtml — water-fill zone gating", () => {
  it("omits the fill zone when the whole window is dry (even with POP)", () => {
    const popOnly = [
      { time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, precipitation_probability: 40, rain_mm: 0, snow_cm: 0 },
    ];
    const html = buildHourlyStripHtml(popOnly, hass24, { showDayBands: false });
    expect(html).not.toContain("ecs-fill");
    expect(html).not.toContain("ecs-vessel");
    // POP-only hour still shows its % in the cluster.
    expect(html).toContain("40%");
  });

  it("renders the fill zone when any hour has a real amount", () => {
    const amtOnly = [
      { time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, precipitation_probability: 0, rain_mm: 2, snow_cm: 0 },
    ];
    const html = buildHourlyStripHtml(amtOnly, hass24, { showDayBands: false });
    expect(html).toContain("ecs-fill");
    expect(html).toContain("ecs-vessel");
    expect(html).toContain("2mm");
  });

  it("a dry hour in a wet window keeps an empty (invisible) vessel", () => {
    const mixed = [
      { time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, rain_mm: 2 },
      { time: "2026-01-07T10:00:00", temp: 5, icon_code: 1, rain_mm: 0 },
    ];
    const html = buildHourlyStripHtml(mixed, hass24, { showDayBands: false });
    // One vessel per hour — the dry one reserves the space with no fill.
    expect((html.match(/ecs-vessel/g) || []).length).toBe(2);
    expect((html.match(/background:var\(--ecw-rain\)/g) || []).length).toBe(1);
  });
});

describe("buildHourlyStripHtml — water-fill heights", () => {
  it("the window's max hour fills the whole 30px vessel; others scale to it", () => {
    const series = [
      { time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, rain_mm: 1 },
      { time: "2026-01-07T10:00:00", temp: 5, icon_code: 1, rain_mm: 2 },
    ];
    const html = buildHourlyStripHtml(series, hass24, { showDayBands: false });
    expect(html).toContain("height:30px;background:var(--ecw-rain)");
    expect(html).toContain("height:15px;background:var(--ecw-rain)");
  });

  it("a trace amount never drops below the 3px visibility floor", () => {
    const series = [
      { time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, rain_mm: 0.1 },
      { time: "2026-01-07T10:00:00", temp: 5, icon_code: 1, rain_mm: 10 },
    ];
    const html = buildHourlyStripHtml(series, hass24, { showDayBands: false });
    expect(html).toContain("height:3px;background:var(--ecw-rain)");
    expect(html).toContain("<1mm");
  });

  it("snow stacks above rain (offset by the rain height), rain corners squared", () => {
    const mixedHour = [
      { time: "2026-01-07T09:00:00", temp: 0, icon_code: 7, rain_mm: 1, snow_cm: 1 },
    ];
    const html = buildHourlyStripHtml(mixedHour, hass24, { showDayBands: false });
    // rain 1 of max total 2 → 15px; snow sits on top of it.
    expect(html).toContain("bottom:15px");
    expect(html).toContain("background:var(--ecw-snowbar)");
    // Rain loses its rounded top when snow stacks above.
    expect(html).toContain("background:var(--ecw-rain);border-radius:0");
    // Compact mixed label: "1mm 1cm" (rain then snow, no spaces inside units).
    expect(html).toContain("1mm");
    expect(html).toContain("1cm");
  });
});

describe("buildHourlyStripHtml — compact modifier", () => {
  it("adds the ecs-strip-compact modifier only when compact", () => {
    const one = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1 }];
    expect(buildHourlyStripHtml(one, hass24, { compact: true, showDayBands: false }))
      .toContain("ecs-strip-compact");
    expect(buildHourlyStripHtml(one, hass24, {}))
      .not.toContain("ecs-strip-compact");
  });

  it("drives column width from colWidth (60px in the popup preset)", () => {
    const one = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1 }];
    const html = buildHourlyStripHtml(one, hass24, { colWidth: 60, showDayBands: false });
    expect(html).toContain("width:60px");
    expect(html).not.toContain("width:64px");
  });

  it("drives the chart height from curveGeometry", () => {
    const one = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1 }];
    const card = buildHourlyStripHtml(one, hass24, {});
    const popup = buildHourlyStripHtml(one, hass24, {
      curveGeometry: { chartHeight: 42, plotTop: 6, plotHeight: 24 }, showDayBands: false,
    });
    expect(card).toContain('height="50"');
    expect(popup).toContain('height="42"');
  });

  it("drives the vessel size from vesselWidth/vesselHeight (popup preset 34x28)", () => {
    const wet = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: 1, rain_mm: 2 }];
    const html = buildHourlyStripHtml(wet, hass24, {
      showDayBands: false, vesselWidth: 34, vesselHeight: 28,
    });
    expect(html).toContain("width:34px;height:28px");
    expect(html).toContain("height:28px;background:var(--ecw-rain)");
  });
});

describe("buildHourlyStripHtml — curve edge cases", () => {
  it("draws a dot for a temperature isolated between gaps", () => {
    const isolated = [
      { time: "2026-01-07T09:00:00", temp: null, icon_code: null, precipitation_probability: null },
      { time: "2026-01-07T10:00:00", temp: 15, icon_code: 1, precipitation_probability: null },
      { time: "2026-01-07T11:00:00", temp: null, icon_code: null, precipitation_probability: null },
    ];
    const html = buildHourlyStripHtml(isolated, hass24, { showDayBands: false });
    expect(html).toContain("<circle");
  });

  it("leaves the temp cell blank when the temperature is null", () => {
    const withGap = [
      { time: "2026-01-07T09:00:00", temp: null, icon_code: 1 },
      { time: "2026-01-07T10:00:00", temp: 12, icon_code: 1 },
    ];
    const html = buildHourlyStripHtml(withGap, hass24, { showDayBands: false });
    // The null hour's temp cell has no degree glyph.
    expect(html).toContain('<div class="ecs-temp"></div>');
    expect(html).toContain("12°");
  });

  it("renders a quiet dash for a missing per-hour icon", () => {
    const noIcon = [{ time: "2026-01-07T09:00:00", temp: 5, icon_code: null }];
    const html = buildHourlyStripHtml(noIcon, hass24, { showDayBands: false });
    expect(html).toContain("mdi:minus");
  });
});

describe("buildHourlyStripHtml — temperature-gradient curve stroke", () => {
  it("strokes the curve with an ecs-curve-stroke gradient, one stop per present temp", () => {
    const html = buildHourlyStripHtml(seriesOf([-20, 0, 25]), hass24, { showDayBands: false });
    expect(html).toContain('id="ecs-curve-stroke"');
    expect(html).toContain('stroke="url(#ecs-curve-stroke)"');
    const grad = strokeGradient(html);
    expect((grad.match(/<stop /g) || []).length).toBe(3);
  });

  it("colors each stop by the absolute-temperature bucket", () => {
    const grad = strokeGradient(buildHourlyStripHtml(seriesOf([-20, 25]), hass24, { showDayBands: false }));
    // -20 → frigid, 25 → hot (same scale as the daily range bars).
    expect(grad).toContain("#6a7fd0");
    expect(grad).toContain("#e59b5b");
    // stop-color rides in style= so the CSS var()+fallback resolves.
    expect(grad).toContain("style=\"stop-color:" + tempColor(-20));
  });

  it("orders offsets 0→1 along the path extent (first=0, last=1)", () => {
    const grad = strokeGradient(buildHourlyStripHtml(seriesOf([-20, 0, 25]), hass24, { showDayBands: false }));
    const offsets = [...grad.matchAll(/offset="([\d.]+)"/g)].map((m) => Number(m[1]));
    expect(offsets[0]).toBe(0);
    expect(offsets[offsets.length - 1]).toBe(1);
    for (let i = 1; i < offsets.length; i++) expect(offsets[i]).toBeGreaterThan(offsets[i - 1]);
  });

  it("emits a stop only for present temps across a gap", () => {
    const grad = strokeGradient(buildHourlyStripHtml(seriesOf([1, null, 3]), hass24, { showDayBands: false }));
    expect((grad.match(/<stop /g) || []).length).toBe(2);
  });

  it("does not crash on a single point; the isolated dot carries its temp color", () => {
    const html = buildHourlyStripHtml(seriesOf([5]), hass24, { showDayBands: false });
    expect(html).toContain("<circle");
    // 5 → cold bucket; the dot is temp-colored, not --ecw-curve.
    expect(html).toContain('fill="' + tempColor(5) + '"');
    expect(html).toContain("#4fa6cf");
  });

  it("leaves the area fill on the unchanged --ecw-curve tint", () => {
    const html = buildHourlyStripHtml(seriesOf([-20, 0, 25]), hass24, { showDayBands: false });
    expect(html).toContain('id="ecs-curve-fill"');
    expect(html).toContain('fill="url(#ecs-curve-fill)"');
    expect(strokeGradient(html)).not.toContain("--ecw-curve");
  });
});

describe("buildHourlyStripHtml — clock preference", () => {
  const one = [{ time: "2026-01-07T00:00:00", temp: 5, icon_code: 1 }];

  it("respects a 24h locale", () => {
    expect(buildHourlyStripHtml(one, hass24, { showDayBands: false })).toContain("00:00");
  });

  it("respects a 12h locale", () => {
    expect(buildHourlyStripHtml(one, hass12, { showDayBands: false })).toContain("12 AM");
  });
});

describe("strip cells never exceed their declared column width", () => {
  // jsdom computes no layout, so the real regression check was a headless-
  // browser measurement: content-box let .ecs-daylbl's 2px padding widen
  // every cell to 66px (44 columns → 88px of phantom scroll). Pin the
  // border-box rule that keeps padding inside the declared width.
  it("STRIP_CSS forces border-box on the strip subtree", async () => {
    const { readFileSync } = await import("node:fs");
    // vitest runs with cwd = www/, next to the card module.
    const source = readFileSync("ec-weather-card.js", "utf8");
    const stripCss = source.slice(
      source.indexOf("const STRIP_CSS"), source.indexOf("const STRIP_DEFAULTS"));
    expect(stripCss).toContain(".ecs-strip, .ecs-strip * { box-sizing: border-box; }");
  });
});
