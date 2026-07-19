/**
 * Daily-popup redesign — pure helpers.
 *
 * popupPeriodModel derives the Day/Night card model (normal vs "passed"),
 * and the wind/POP/precip line rules. buildHourlyCurve gained a geometry
 * parameter for the popup's shorter chart; the default must stay byte-for-byte
 * identical to the card's original hardcoded formula.
 */

import { describe, expect, it } from "vitest";

import { buildHourlyCurve, popupPeriodModel } from "../ec-weather-card.js";

describe("popupPeriodModel — passed detection", () => {
  it("day half with icon_code null → passed (day is over)", () => {
    const item = { icon_code: null, icon_code_night: 30, temp_high: null, temp_low: 16 };
    expect(popupPeriodModel(item, "day")).toEqual({ passed: true });
  });

  it("night half is never passed even when icon_code is null", () => {
    const item = { icon_code: null, icon_code_night: 30, temp_high: null, temp_low: 16 };
    expect(popupPeriodModel(item, "night").passed).toBe(false);
  });

  it("day half with a real icon_code is not passed", () => {
    const item = { icon_code: 5, temp_high: 22 };
    expect(popupPeriodModel(item, "day").passed).toBe(false);
  });
});

describe("popupPeriodModel — temperature and icon selection", () => {
  it("day uses temp_high, night uses temp_low", () => {
    const item = { icon_code: 1, temp_high: 24, temp_low: 12 };
    expect(popupPeriodModel(item, "day").temp).toBe(24);
    expect(popupPeriodModel(item, "night").temp).toBe(12);
  });

  it("null temp stays null (no fabricated zero)", () => {
    const item = { icon_code: 1, temp_high: null };
    expect(popupPeriodModel(item, "day").temp).toBeNull();
  });

  it("day icon is icon_code; night prefers icon_code_night", () => {
    const item = { icon_code: 5, icon_code_night: 31, temp_high: 20, temp_low: 10 };
    expect(popupPeriodModel(item, "day").iconCode).toBe(5);
    expect(popupPeriodModel(item, "night").iconCode).toBe(31);
  });

  it("night falls back to icon_code when icon_code_night is null", () => {
    const item = { icon_code: 5, icon_code_night: null, temp_high: 20, temp_low: 10 };
    expect(popupPeriodModel(item, "night").iconCode).toBe(5);
  });

  it("night icon null when both are absent", () => {
    const item = { icon_code: null, icon_code_night: null, temp_low: 10 };
    // (day would be 'passed'; only night is exercised here)
    expect(popupPeriodModel(item, "night").iconCode).toBeNull();
  });
});

describe("popupPeriodModel — wind line rules", () => {
  it("null wind → hidden (no line)", () => {
    const item = { icon_code: 1, wind_speed: null };
    expect(popupPeriodModel(item, "day").windState).toBe("hidden");
  });

  it("0 wind → calm", () => {
    const item = { icon_code: 1, wind_speed: 0, wind_direction: "NW" };
    expect(popupPeriodModel(item, "day").windState).toBe("calm");
  });

  it("real wind → value, gusts kept even when 0", () => {
    const item = { icon_code: 1, wind_speed: 20, wind_gust: 0, wind_direction: "NW" };
    const model = popupPeriodModel(item, "day");
    expect(model.windState).toBe("value");
    expect(model.windSpeed).toBe(20);
    expect(model.windGust).toBe(0);
    expect(model.windDirection).toBe("NW");
  });

  it("night reads the _night wind variants", () => {
    const item = {
      icon_code: 1, icon_code_night: 30, temp_low: 10,
      wind_speed_night: 15, wind_gust_night: 30, wind_direction_night: "S",
    };
    const model = popupPeriodModel(item, "night");
    expect(model.windState).toBe("value");
    expect(model.windSpeed).toBe(15);
    expect(model.windDirection).toBe("S");
  });
});

describe("popupPeriodModel — POP and precip line rules", () => {
  it("POP null → no pop line", () => {
    const item = { icon_code: 1, precip_prob_day: null };
    expect(popupPeriodModel(item, "day").pop).toBeNull();
  });

  it("POP is a pure passthrough of the backend-stepped value", () => {
    // The backend hides sub-floor POPs (emitting null) and rounds the rest up,
    // so the box prints exactly what it receives — no rounding or 0-gate here.
    const item = { icon_code: 1, precip_prob_day: 75 };
    expect(popupPeriodModel(item, "day").pop).toBe(75);
    const stepped = { icon_code: 1, precip_prob_day: 25 };
    expect(popupPeriodModel(stepped, "day").pop).toBe(25);
  });

  it("only precip types > 0 render (rain/snow independent)", () => {
    const item = { icon_code: 1, rain_mm_day: 2.4, snow_cm_day: 0 };
    const model = popupPeriodModel(item, "day");
    expect(model.showRain).toBe(true);
    expect(model.showSnow).toBe(false);
    expect(model.rain).toBe(2.4);
  });

  it("night precip reads the _night variants", () => {
    const item = { icon_code: 1, icon_code_night: 30, temp_low: 10, snow_cm_night: 3 };
    const model = popupPeriodModel(item, "night");
    expect(model.showSnow).toBe(true);
    expect(model.showRain).toBe(false);
    expect(model.snow).toBe(3);
  });

  it("backend-resolved precip_amount_day wins over legacy fields", () => {
    // EC-stated 5mm resolved by the backend; legacy WEonG field ignored.
    const item = {
      icon_code: 1,
      rain_mm_day: 99,
      precip_amount_day: { rain_mm: 5, snow_cm: 0, estimated: false },
    };
    const model = popupPeriodModel(item, "day");
    expect(model.rain).toBe(5);
    expect(model.estimated).toBe(false);
  });

  it("resolved estimated flag drives the tilde provenance", () => {
    const item = {
      icon_code: 1,
      precip_amount_day: { rain_mm: 2, snow_cm: 0.5, estimated: true },
    };
    const model = popupPeriodModel(item, "day");
    expect(model.rain).toBe(2);
    expect(model.snow).toBe(0.5);
    expect(model.estimated).toBe(true);
  });

  it("legacy items (no resolved field) fall back as estimates", () => {
    const item = { icon_code: 1, rain_mm_day: 2.4 };
    const model = popupPeriodModel(item, "day");
    expect(model.rain).toBe(2.4);
    expect(model.estimated).toBe(true);
  });
});

describe("popupPeriodModel — feels-like line rules", () => {
  it("day reads feels_like_high, night reads feels_like_low", () => {
    const item = { icon_code: 1, icon_code_night: 30, temp_high: 20, temp_low: 8, feels_like_high: 25, feels_like_low: 3 };
    expect(popupPeriodModel(item, "day").feels).toBe(25);
    expect(popupPeriodModel(item, "night").feels).toBe(3);
  });

  it("shown when feels differs from temp after rounding", () => {
    const item = { icon_code: 1, temp_high: 20, feels_like_high: 25 };
    expect(popupPeriodModel(item, "day").showFeels).toBe(true);
  });

  it("hidden when feels-like is absent", () => {
    const item = { icon_code: 1, temp_high: 20, feels_like_high: null };
    const model = popupPeriodModel(item, "day");
    expect(model.showFeels).toBe(false);
    expect(model.feels).toBeNull();
  });

  it("hidden when feels equals temp after rounding", () => {
    const item = { icon_code: 1, temp_high: 20, feels_like_high: 20.3 };
    expect(popupPeriodModel(item, "day").showFeels).toBe(false);
  });

  it("hidden when temp is absent (nothing to compare against)", () => {
    const item = { icon_code: 1, temp_high: null, feels_like_high: 25 };
    expect(popupPeriodModel(item, "day").showFeels).toBe(false);
  });
});

describe("popupPeriodModel — humidity line rules", () => {
  it("day reads humidity, night reads humidity_night", () => {
    const item = { icon_code: 1, icon_code_night: 30, temp_low: 8, humidity: 55, humidity_night: 80 };
    expect(popupPeriodModel(item, "day").humidity).toBe(55);
    expect(popupPeriodModel(item, "night").humidity).toBe(80);
  });

  it("null humidity → hidden (no value)", () => {
    const item = { icon_code: 1, humidity: null };
    expect(popupPeriodModel(item, "day").humidity).toBeNull();
  });
});

describe("popupPeriodModel — UV line rules (Day card only)", () => {
  it("day carries uv_index and uv_category", () => {
    const item = { icon_code: 1, temp_high: 20, uv_index: 9, uv_category: "very high" };
    const model = popupPeriodModel(item, "day");
    expect(model.uvIndex).toBe(9);
    expect(model.uvCategory).toBe("very high");
  });

  it("night uv is always null even when the item carries a uv_index", () => {
    const item = { icon_code: 1, icon_code_night: 30, temp_low: 8, uv_index: 9, uv_category: "very high" };
    const model = popupPeriodModel(item, "night");
    expect(model.uvIndex).toBeNull();
    expect(model.uvCategory).toBeNull();
  });

  it("day uv null when the item omits uv_index", () => {
    const item = { icon_code: 1, temp_high: 20 };
    expect(popupPeriodModel(item, "day").uvIndex).toBeNull();
  });
});

describe("buildHourlyCurve — default geometry is a regression pin", () => {
  it("two present temps: exact path and area (unchanged from the card)", () => {
    const curve = buildHourlyCurve([10, 20], 64);
    expect(curve.path).toBe("M 32,40 L 96,10");
    expect(curve.areaPath).toBe("M 32,40 96,10 L 96,50 L 32,50 Z");
    expect(curve.allPresent).toBe(true);
  });

  it("gap in the middle breaks the path and drops the area fill", () => {
    const curve = buildHourlyCurve([10, null, 20], 64);
    expect(curve.path).toBe("M 32,40 M 160,10");
    expect(curve.areaPath).toBeNull();
    // Both flanking-null points are isolated → dots.
    expect(curve.points[0].isolated).toBe(true);
    expect(curve.points[2].isolated).toBe(true);
    expect(curve.points[1]).toBeNull();
  });
});

describe("buildHourlyCurve — popup geometry fits the 42px chart", () => {
  const GEOM = { chartHeight: 42, plotTop: 6, plotHeight: 24 };

  it("y values land inside the plot band [6,30]", () => {
    const curve = buildHourlyCurve([10, 20], 60, GEOM);
    expect(curve.path).toBe("M 30,30 L 90,6");
    for (const point of curve.points) {
      expect(point.y).toBeGreaterThanOrEqual(6);
      expect(point.y).toBeLessThanOrEqual(30);
    }
  });

  it("area fill baselines at chartHeight (42), not the card's 50", () => {
    const curve = buildHourlyCurve([10, 20], 60, GEOM);
    expect(curve.areaPath).toBe("M 30,30 90,6 L 90,42 L 30,42 Z");
  });
});
