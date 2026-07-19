/**
 * Behavioral baseline for the card's pure helpers — the functions the Python
 * source-text assertions can only prove exist. Bucket boundaries, formatting
 * rules and precedence orders are exercised with real inputs here.
 */

import { describe, expect, it } from "vitest";

import {
  aqhiRiskColor,
  dailyIconColor,
  dailyPrecip,
  dailyTempRange,
  escapeHtml,
  fmtAmt,
  fmtAmtUnit,
  liquidTotal,
  precipAmtLabels,
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

describe("aqhiRiskColor — risk-level lookup (no numeric thresholds in JS)", () => {
  it("absent / unknown risk → null (cell hidden, malformed rejected)", () => {
    expect(aqhiRiskColor(null)).toBeNull();
    expect(aqhiRiskColor(undefined)).toBeNull();
    expect(aqhiRiskColor("")).toBeNull();
    expect(aqhiRiskColor("garbage")).toBeNull();
    // A raw numeric AQHI must not be mistaken for a risk level.
    expect(aqhiRiskColor(4)).toBeNull();
  });
  it("maps each backend risk_level to its token colour", () => {
    expect(aqhiRiskColor("low")).toContain("#4f9fd0");
    expect(aqhiRiskColor("moderate")).toContain("#dcae4e");
    expect(aqhiRiskColor("high")).toContain("#e08a3f");
    expect(aqhiRiskColor("very_high")).toContain("#d1495b");
  });
  it("every bucket is publicly overridable", () => {
    expect(aqhiRiskColor("low")).toMatch(/^var\(--ec-weather-aqhi-/);
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
  it("POP is a pure passthrough of the backend-stepped value — no ceil here", () => {
    // The backend already rounded up to the next 5 and hid sub-floor POPs
    // (emitting null). The card only takes the max of the shown halves.
    expect(dailyPrecip({ precip_prob_day: 65 }).popRounded).toBe(65);
    expect(dailyPrecip({ precip_prob_day: 25 }).popRounded).toBe(25);
    expect(dailyPrecip({ precip_prob_day: 25 }).showPrecip).toBe(true);
    // A hidden half arrives as null; both null → nothing to show.
    expect(dailyPrecip({ precip_prob_day: null }).showPrecip).toBe(false);
    expect(dailyPrecip({ precip_prob_day: null }).popRounded).toBeNull();
    // Max of the two shown halves wins.
    expect(dailyPrecip({ precip_prob_day: 20, precip_prob_night: 45 }).popRounded).toBe(45);
    expect(dailyPrecip({ precip_prob_day: 30, precip_prob_night: null }).popRounded).toBe(30);
  });
  it("cm accumulation counts as snow", () => {
    const summary = dailyPrecip({
      precip_accum_amount: 4,
      precip_accum_unit: "cm",
    });
    expect(summary.snowAmt).toBe(4);
    expect(summary.rainAmt).toBe(0);
  });
  it("null model amount fields show no amount (option OFF, data-driven gating)", () => {
    // When model_precip_estimate is off, the sensor sends null model fields.
    // dailyPrecip must treat them as "no amount" (0), never NaN or a stray
    // value, so the card renders POP only and no amount.
    const summary = dailyPrecip({
      precip_prob_day: 40,
      rain_mm_day: null,
      snow_cm_day: null,
      rain_mm_night: null,
      snow_cm_night: null,
    });
    expect(summary.rainAmt).toBe(0);
    expect(summary.snowAmt).toBe(0);
    expect(summary.popRounded).toBe(40);
    expect(summary.showPrecip).toBe(true);
  });
  it("EC-stated accumulation still shows when model fields are null (option OFF)", () => {
    // Gating only suppresses the model fallback; a meteorologist-stated EC
    // accumulation is unaffected and still rendered.
    const summary = dailyPrecip({
      precip_prob_day: 60,
      precip_accum_amount: 5,
      precip_accum_unit: "mm",
      rain_mm_day: null,
      snow_cm_day: null,
    });
    expect(summary.rainAmt).toBe(5);
    expect(summary.snowAmt).toBe(0);
  });
  it("flags model-derived amounts as estimated (day, night, cm variants)", () => {
    // The model fallback (the "Estimated precipitation amounts" beta) yields
    // probability-weighted expected totals — marked estimated so the renderers
    // prepend a "~".
    expect(dailyPrecip({ precip_prob_day: 40, rain_mm_day: 2, snow_cm_day: 1 }).estimated).toBe(true);
    expect(dailyPrecip({ rain_mm_night: 3 }).estimated).toBe(true);
    expect(dailyPrecip({ snow_cm_night: 4 }).estimated).toBe(true);
  });
  it("flags EC-stated accumulation as NOT estimated (mm day, mm night, cm)", () => {
    // A meteorologist's committed accumulation renders as-is (no tilde).
    expect(dailyPrecip({ precip_accum_amount: 5, precip_accum_unit: "mm" }).estimated).toBe(false);
    expect(dailyPrecip({ precip_accum_amount_night: 4, precip_accum_unit_night: "mm" }).estimated).toBe(false);
    expect(dailyPrecip({ precip_accum_amount: 4, precip_accum_unit: "cm" }).estimated).toBe(false);
  });
  it("estimated tracks the branch, not the amounts — both-zero takes the model branch (true) but is inert (no amount renders)", () => {
    // Convention: `estimated` reflects WHICH branch produced the amounts, not
    // whether they are nonzero. With neither EC accumulation nor model amounts,
    // the model fallback branch runs → estimated=true, but both amounts are 0
    // so nothing is displayed and the flag never surfaces a tilde.
    const summary = dailyPrecip({ precip_prob_day: 40 });
    expect(summary.rainAmt).toBe(0);
    expect(summary.snowAmt).toBe(0);
    expect(summary.estimated).toBe(true);
  });
});

describe("precipAmtLabels — the one place the tilde convention + mm/cm format live", () => {
  // Shared by every compact amount render site (daily column + float, today
  // panel chips, popup day/night boxes). Returns the marked, unit-formatted
  // label for each component, or null when that component is absent/zero so the
  // call site gates exactly as it did on `rain > 0` / `snow > 0`.

  it("EC-stated (estimated falsy): bare labels, never a tilde", () => {
    expect(precipAmtLabels(8, 0, false)).toEqual({ rain: "8mm", snow: null });
    expect(precipAmtLabels(0, 4, false)).toEqual({ rain: null, snow: "4cm" });
  });

  it("model estimate, rain only: the rain amount wears the tilde", () => {
    expect(precipAmtLabels(8, 0, true)).toEqual({ rain: "~8mm", snow: null });
  });

  it("model estimate, snow only: the sole amount (snow) wears the tilde", () => {
    expect(precipAmtLabels(0, 6, true)).toEqual({ rain: null, snow: "~6cm" });
  });

  it("model estimate, rain + snow: ONE tilde leads the group (rain), snow bare", () => {
    expect(precipAmtLabels(12, 8, true)).toEqual({ rain: "~12mm", snow: "8cm" });
  });

  it("zero amounts return null components — call sites render nothing", () => {
    expect(precipAmtLabels(0, 0, true)).toEqual({ rain: null, snow: null });
    expect(precipAmtLabels(0, 0, false)).toEqual({ rain: null, snow: null });
  });

  it("sub-1 amounts keep the compact '<1' form; the tilde still leads", () => {
    expect(precipAmtLabels(0.4, 0, true)).toEqual({ rain: "~<1mm", snow: null });
    expect(precipAmtLabels(0.4, 0, false)).toEqual({ rain: "<1mm", snow: null });
  });

  it("estimated=false is honest to its flag — never tildes even a mixed group", () => {
    expect(precipAmtLabels(12, 8, false)).toEqual({ rain: "12mm", snow: "8cm" });
  });
});

describe("dailyTempRange — partial-period range from hourly timesteps", () => {
  it("missing high (Tonight): derives both ends from the hourly temps", () => {
    const range = dailyTempRange({
      temp_low: 16,
      temp_high: null,
      timesteps_night: [{ temp: 25 }, { temp: 20 }, { temp: 16 }],
    });
    expect(range).toEqual({ low: 16, high: 25, derived: true });
  });

  it("missing low: symmetric — derives both ends from the hourly temps", () => {
    const range = dailyTempRange({
      temp_low: null,
      temp_high: 22,
      timesteps_day: [{ temp: 14 }, { temp: 22 }, { temp: 18 }],
    });
    expect(range).toEqual({ low: 14, high: 22, derived: true });
  });

  it("combines day and night timesteps for the derived range", () => {
    const range = dailyTempRange({
      temp_low: 16,
      temp_high: null,
      timesteps_day: [{ temp: 28 }, { temp: 26 }],
      timesteps_night: [{ temp: 21 }, { temp: 17 }],
    });
    expect(range).toEqual({ low: 17, high: 28, derived: true });
  });

  it("filters null and non-numeric temps before deriving", () => {
    const range = dailyTempRange({
      temp_low: 16,
      temp_high: null,
      timesteps_night: [{ temp: null }, { temp: "n/a" }, { temp: 19 }, {}, { temp: 12 }],
    });
    expect(range).toEqual({ low: 12, high: 19, derived: true });
  });

  it("no usable timesteps: passthrough (single-point behavior preserved)", () => {
    expect(dailyTempRange({ temp_low: 16, temp_high: null }))
      .toEqual({ low: 16, high: null, derived: false });
    expect(dailyTempRange({ temp_low: 16, temp_high: null, timesteps_night: [] }))
      .toEqual({ low: 16, high: null, derived: false });
    expect(dailyTempRange({ temp_low: 16, temp_high: null, timesteps_night: [{ temp: null }] }))
      .toEqual({ low: 16, high: null, derived: false });
  });

  it("both bounds present: never overridden even with timesteps", () => {
    const range = dailyTempRange({
      temp_low: 14,
      temp_high: 22,
      timesteps_day: [{ temp: 5 }, { temp: 40 }],
    });
    expect(range).toEqual({ low: 14, high: 22, derived: false });
  });

  it("both bounds null: passthrough (nothing to derive against)", () => {
    const range = dailyTempRange({
      temp_low: null,
      temp_high: null,
      timesteps_day: [{ temp: 18 }],
    });
    expect(range).toEqual({ low: null, high: null, derived: false });
  });
});
