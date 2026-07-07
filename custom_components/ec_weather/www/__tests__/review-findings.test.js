/**
 * Behavioral tests for the redesign review findings (fixed as one batch).
 * Each describe block names the defect it guards against; every case here
 * failed (or was unwritable) under the pre-fix code.
 */

import { describe, expect, it } from "vitest";

import {
  aqhiColor,
  buildHourlyCurve,
  dailyPrecip,
  isEmptyTimestep,
  precipPanelHead,
  rangeBarGeometry,
  sunCellMode,
  uvColor,
  windCellState,
} from "../ec-weather-card.js";

describe("finding 1 — panel header must not say 'None expected' over a real POP", () => {
  it("POP 60 with zero amounts → chance header, not none-expected", () => {
    const summary = dailyPrecip({ precip_prob_day: 60 });
    expect(precipPanelHead(summary)).toEqual({ kind: "chance", popRounded: 60 });
  });

  it("dry day (no POP, no amounts) → none-expected", () => {
    const summary = dailyPrecip({ precip_prob_day: 0 });
    expect(precipPanelHead(summary).kind).toBe("none-expected");
  });

  it("no forecast data at all → empty header, no dry-day claim", () => {
    expect(precipPanelHead(null).kind).toBe("empty");
  });

  it("amounts without a POP → empty header (amounts live in the row)", () => {
    const summary = dailyPrecip({ rain_mm_day: 3 });
    expect(precipPanelHead(summary).kind).toBe("empty");
  });

  it("POP and amounts → chance header", () => {
    const summary = dailyPrecip({ precip_prob_day: 70, rain_mm_day: 3, snow_cm_day: 5 });
    expect(precipPanelHead(summary)).toEqual({ kind: "chance", popRounded: 70 });
  });
});

describe("finding 3 — wind cell never fabricates 'Calm' from missing data", () => {
  it("null (sensor unknown) → cell hidden", () => {
    expect(windCellState(null)).toBe("hidden");
  });
  it("0 km/h → calm", () => {
    expect(windCellState(0)).toBe("calm");
  });
  it("sub-1 km/h rounds to calm", () => {
    expect(windCellState(0.4)).toBe("calm");
  });
  it("real wind → value", () => {
    expect(windCellState(12)).toBe("value");
  });
});

describe("finding 4 — polar states only at polar latitudes", () => {
  it("both times present → arc, regardless of latitude", () => {
    expect(sunCellMode("05:11", "20:49", 45.5, "above_horizon")).toBe("arc");
  });
  it("missing times at 45°N → hidden, never a polar claim", () => {
    expect(sunCellMode(null, null, 45.5, "above_horizon")).toBe("hidden");
    expect(sunCellMode(null, null, 45.5, "below_horizon")).toBe("hidden");
  });
  it("missing times at 70°N → polar day/night by sun elevation", () => {
    expect(sunCellMode(null, null, 70, "above_horizon")).toBe("polar-day");
    expect(sunCellMode(null, null, 70, "below_horizon")).toBe("polar-night");
  });
  it("high latitude but sun integration absent → hidden, not a guess", () => {
    expect(sunCellMode(null, null, 70, null)).toBe("hidden");
  });
  it("unknown latitude → hidden", () => {
    expect(sunCellMode(null, null, null, "below_horizon")).toBe("hidden");
  });
  it("partial data (one of the two times) → hidden at mid-latitudes", () => {
    expect(sunCellMode(null, "20:49", 45.5, "above_horizon")).toBe("hidden");
  });
  it("southern hemisphere polar latitudes count too", () => {
    expect(sunCellMode(null, null, -78, "above_horizon")).toBe("polar-day");
  });
});

describe("finding 8 (empty timesteps) — all-null hours are skipped again", () => {
  it("temp, icon and POP all null → empty", () => {
    expect(isEmptyTimestep({ temp: null, icon_code: null, precipitation_probability: null })).toBe(true);
    expect(isEmptyTimestep({})).toBe(true);
  });
  it("any of the three present → kept (0 is a real POP)", () => {
    expect(isEmptyTimestep({ temp: -3 })).toBe(false);
    expect(isEmptyTimestep({ icon_code: 0 })).toBe(false);
    expect(isEmptyTimestep({ precipitation_probability: 0 })).toBe(false);
  });
});

describe("finding 7 — isolated curve points render as dots, not invisible subpaths", () => {
  it("a temp surrounded by gaps is flagged isolated", () => {
    const curve = buildHourlyCurve([null, -3, null, null, 5, 6]);
    const present = curve.points.filter(Boolean);
    expect(present).toHaveLength(3);
    expect(present[0].isolated).toBe(true);
    expect(present[1].isolated).toBe(false);
    expect(present[2].isolated).toBe(false);
  });
  it("a single-hour window is one isolated point", () => {
    const curve = buildHourlyCurve([5]);
    expect(curve.points[0].isolated).toBe(true);
  });
  it("gap windows lose the area fill; complete windows keep it", () => {
    expect(buildHourlyCurve([null, -3, null, null, 5, 6]).areaPath).toBeNull();
    expect(buildHourlyCurve([1, 2, 3]).areaPath).not.toBeNull();
    expect(buildHourlyCurve([1, 2, 3]).points.every((p) => !p.isolated)).toBe(true);
  });
  it("missing temps produce no point and break the path", () => {
    const curve = buildHourlyCurve([1, null, 3]);
    expect(curve.points[1]).toBeNull();
    expect((curve.path.match(/M /g) || []).length).toBe(2);
  });
});

describe("finding 9 — range bar span stays inside the track", () => {
  it("narrow range at the top of the week's scale is clamped to 100%", () => {
    const bar = rangeBarGeometry(9, 10, -20, 10);
    expect(bar.kind).toBe("span");
    expect(bar.width).toBe(6);
    expect(bar.left + bar.width).toBeLessThanOrEqual(100);
  });
  it("narrow range at the bottom keeps left >= 0", () => {
    const bar = rangeBarGeometry(-20, -19, -20, 10);
    expect(bar.left).toBeGreaterThanOrEqual(0);
    expect(bar.left + bar.width).toBeLessThanOrEqual(100);
  });
  it("normal span is untouched", () => {
    const bar = rangeBarGeometry(0, 10, -10, 20);
    expect(bar.kind).toBe("span");
    expect(bar.left).toBeCloseTo(33.33, 1);
    expect(bar.left + bar.width).toBeCloseTo(66.67, 1);
  });
  it("single value → dot", () => {
    expect(rangeBarGeometry(5, null, 0, 10)).toEqual({ kind: "dot", left: 50, value: 5 });
    expect(rangeBarGeometry(null, 8, 0, 10).kind).toBe("dot");
  });
  it("low == high → dot", () => {
    expect(rangeBarGeometry(5, 5, 0, 10).kind).toBe("dot");
  });
  it("isothermal week centers the dot", () => {
    expect(rangeBarGeometry(5, null, 5, 5).left).toBe(50);
  });
  it("no temps → none", () => {
    expect(rangeBarGeometry(null, null, 0, 10).kind).toBe("none");
  });
});

describe("finding 6 hardening — risk colors reject non-numeric values", () => {
  it("uvColor: strings never resolve to a color (blocks HTML-injection path)", () => {
    expect(uvColor("9")).toBeNull();
    expect(uvColor("<img src=x onerror=alert(1)>")).toBeNull();
    expect(uvColor(NaN)).toBeNull();
  });
  it("aqhiColor gets the same gate", () => {
    expect(aqhiColor("4")).toBeNull();
    expect(aqhiColor(NaN)).toBeNull();
  });
  it("real numbers still work", () => {
    expect(uvColor(9)).toContain("#d1495b");
    expect(aqhiColor(2)).toContain("#4f9fd0");
  });
});
