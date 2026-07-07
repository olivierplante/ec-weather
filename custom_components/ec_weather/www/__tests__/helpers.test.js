/**
 * Behavioral baseline for the card's pure helpers — the functions the Python
 * source-text assertions can only prove exist. Bucket boundaries, formatting
 * rules and precedence orders are exercised with real inputs here.
 */

import { describe, expect, it } from "vitest";

import {
  aqhiColor,
  dailyIconColor,
  dailyPrecip,
  escapeHtml,
  fmtAmt,
  fmtAmtUnit,
  liquidTotal,
  tempColor,
  themeClass,
  use24Hour,
  uvColor,
} from "../ec-weather-card.js";

describe("tempColor — absolute temperature buckets", () => {
  const cases = [
    [-20, "#6a7fd0"],
    [-15, "#6a7fd0"],
    [-14.9, "#5b93d4"],
    [-0.1, "#5b93d4"],
    [0, "#4fa6cf"],
    [5.9, "#4fa6cf"],
    [6, "#5cbf9e"],
    [11.9, "#5cbf9e"],
    [12, "#93c98a"],
    [17.9, "#93c98a"],
    [18, "#dcc079"],
    [23.9, "#dcc079"],
    [24, "#e59b5b"],
    [29.9, "#e59b5b"],
    [30, "#e5793f"],
    [40, "#e5793f"],
  ];
  for (const [temp, hex] of cases) {
    it(`${temp}° resolves to ${hex}`, () => {
      expect(tempColor(temp)).toContain(hex);
    });
  }

  it("every bucket is publicly overridable", () => {
    expect(tempColor(-20)).toMatch(/^var\(--ec-weather-temp-/);
  });
});

describe("aqhiColor — risk buckets", () => {
  it("null → null (cell hidden)", () => {
    expect(aqhiColor(null)).toBeNull();
    expect(aqhiColor(undefined)).toBeNull();
  });
  it("boundaries: 3 low, 4 moderate, 6 moderate, 7 high, 10 high, 11 very high", () => {
    expect(aqhiColor(3)).toContain("#4f9fd0");
    expect(aqhiColor(4)).toContain("#dcae4e");
    expect(aqhiColor(6)).toContain("#dcae4e");
    expect(aqhiColor(7)).toContain("#e08a3f");
    expect(aqhiColor(10)).toContain("#e08a3f");
    expect(aqhiColor(11)).toContain("#d1495b");
  });
});

describe("uvColor — risk buckets", () => {
  it("null → null (cell hidden)", () => {
    expect(uvColor(null)).toBeNull();
  });
  it("boundaries: 2 low, 3 moderate, 6 high, 8 very high, 11 extreme", () => {
    expect(uvColor(2)).toContain("#3f9f6e");
    expect(uvColor(3)).toContain("#dcae4e");
    expect(uvColor(6)).toContain("#e08a3f");
    expect(uvColor(8)).toContain("#d1495b");
    expect(uvColor(11)).toContain("#9b5fb8");
  });
});

describe("use24Hour — clock preference", () => {
  const hass = (time_format, language) => ({ locale: { time_format }, language });
  it("explicit '24' wins over language", () => {
    expect(use24Hour(hass("24", "en"))).toBe(true);
  });
  it("explicit '12' wins over language", () => {
    expect(use24Hour(hass("12", "fr"))).toBe(false);
  });
  it("'language' falls back: fr → 24h, en → 12h", () => {
    expect(use24Hour(hass("language", "fr"))).toBe(true);
    expect(use24Hour(hass("language", "en"))).toBe(false);
  });
  it("missing locale falls back to language default", () => {
    expect(use24Hour({ language: "fr" })).toBe(true);
    expect(use24Hour({ language: "en" })).toBe(false);
  });
});

describe("liquidTotal — 1 cm snow ~ 1 mm water", () => {
  it("sums rain mm and snow cm", () => {
    expect(liquidTotal(3, 5)).toBe(8);
  });
  it("nulls count as zero", () => {
    expect(liquidTotal(null, 2)).toBe(2);
    expect(liquidTotal(4, null)).toBe(4);
    expect(liquidTotal(null, null)).toBe(0);
  });
});

describe("dailyIconColor — condition family precedence", () => {
  it("mixed precip reads as rain, not snow", () => {
    expect(dailyIconColor("mdi:weather-snowy-rainy")).toBe("var(--ecw-rain)");
  });
  it("snow family", () => {
    expect(dailyIconColor("mdi:weather-snowy")).toBe("var(--ecw-snow)");
  });
  it("rain family incl. lightning and pouring", () => {
    expect(dailyIconColor("mdi:weather-rainy")).toBe("var(--ecw-rain)");
    expect(dailyIconColor("mdi:weather-lightning-rainy")).toBe("var(--ecw-rain)");
    expect(dailyIconColor("mdi:weather-pouring")).toBe("var(--ecw-rain)");
  });
  it("sun", () => {
    expect(dailyIconColor("mdi:weather-sunny")).toBe("var(--ecw-sun)");
  });
  it("clouds, fog and night stay neutral", () => {
    expect(dailyIconColor("mdi:weather-cloudy")).toBe("var(--ecw-text2)");
    expect(dailyIconColor("mdi:weather-fog")).toBe("var(--ecw-text2)");
    expect(dailyIconColor("mdi:weather-night")).toBe("var(--ecw-text2)");
  });
});

describe("themeClass — HA theme binding", () => {
  it("dark theme (and older HA without the flag) → ecc", () => {
    expect(themeClass({ themes: { darkMode: true } })).toBe("ecc");
    expect(themeClass({ themes: {} })).toBe("ecc");
    expect(themeClass({})).toBe("ecc");
  });
  it("light theme → ecc light", () => {
    expect(themeClass({ themes: { darkMode: false } })).toBe("ecc light");
  });
});

describe("fmtAmt — precip amount formatting", () => {
  it("trace amounts render as <1", () => {
    expect(fmtAmt(0.4)).toBe("<1");
  });
  it("rounds to whole numbers", () => {
    expect(fmtAmt(2.6)).toBe("3");
  });
  it("zero and null render nothing", () => {
    expect(fmtAmt(0)).toBeNull();
    expect(fmtAmt(null)).toBeNull();
  });
});

describe("fmtAmtUnit — compact amount+unit, no space", () => {
  it("appends the unit with no space", () => {
    expect(fmtAmtUnit(2.6, "mm")).toBe("3mm");
    expect(fmtAmtUnit(5, "cm")).toBe("5cm");
  });
  it("trace amounts keep the compact form", () => {
    expect(fmtAmtUnit(0.4, "mm")).toBe("<1mm");
  });
  it("zero and null render nothing", () => {
    expect(fmtAmtUnit(0, "mm")).toBeNull();
    expect(fmtAmtUnit(null, "cm")).toBeNull();
  });
});

describe("escapeHtml — API strings never reach the DOM raw", () => {
  it("escapes markup characters", () => {
    expect(escapeHtml('<img src=x onerror="x">')).toBe(
      "&lt;img src=x onerror=&quot;x&quot;&gt;",
    );
  });
  it("null-safe", () => {
    expect(escapeHtml(null)).toBe("");
  });
});

describe("dailyPrecip — shared POP/amount source of truth", () => {
  it("prefers EC accumulation over WEonG amounts", () => {
    const summary = dailyPrecip({
      precip_prob_day: 60,
      precip_accum_amount: 5,
      precip_accum_unit: "mm",
      rain_mm_day: 99,
    });
    expect(summary.rainAmt).toBe(5);
    expect(summary.popRounded).toBe(60);
  });
  it("falls back to WEonG rain/snow when EC has no accumulation", () => {
    const summary = dailyPrecip({
      precip_prob_day: 40,
      rain_mm_day: 2,
      snow_cm_day: 1,
      rain_mm_night: 1,
    });
    expect(summary.rainAmt).toBe(3);
    expect(summary.snowAmt).toBe(1);
  });
  it("POP rounds UP to the nearest 5 — any nonzero POP is visible", () => {
    expect(dailyPrecip({ precip_prob_day: 61 }).popRounded).toBe(65);
    expect(dailyPrecip({ precip_prob_day: 4 }).popRounded).toBe(5);
    expect(dailyPrecip({ precip_prob_day: 4 }).showPrecip).toBe(true);
    expect(dailyPrecip({ precip_prob_day: 0 }).showPrecip).toBe(false);
  });
  it("cm accumulation counts as snow", () => {
    const summary = dailyPrecip({
      precip_accum_amount: 4,
      precip_accum_unit: "cm",
    });
    expect(summary.snowAmt).toBe(4);
    expect(summary.rainAmt).toBe(0);
  });
});
