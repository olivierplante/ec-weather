/**
 * nextSunEvent() — the sun-arc caption counts down to whichever event is
 * next: sunset while the sun is up, sunrise otherwise (today's if still
 * ahead, tomorrow's after sunset).
 *
 * sunLoopModel() — the continuous day/night loop: the dot rides the top arc
 * by day (above the horizon, y < 26) and a shallower dip by night (below,
 * y > 26), with the countdown to the next event.
 */

import { describe, expect, it } from "vitest";

import { nextSunEvent, sunLoopModel } from "../ec-weather-card.js";

const RISE = 5 * 60 + 11;  // 05:11
const SET = 20 * 60 + 49;  // 20:49

describe("nextSunEvent", () => {
  it("mid-afternoon → countdown to sunset", () => {
    const at1500 = 15 * 60;
    expect(nextSunEvent(at1500, RISE, SET)).toEqual({
      event: "sunset",
      minutesUntil: SET - at1500,
    });
  });

  it("just after sunrise → still counts to sunset", () => {
    expect(nextSunEvent(RISE, RISE, SET).event).toBe("sunset");
  });

  it("evening after sunset → countdown to tomorrow's sunrise (wraps midnight)", () => {
    const at2200 = 22 * 60;
    expect(nextSunEvent(at2200, RISE, SET)).toEqual({
      event: "sunrise",
      minutesUntil: RISE + 1440 - at2200,
    });
  });

  it("early morning before sunrise → countdown to today's sunrise", () => {
    const at0400 = 4 * 60;
    expect(nextSunEvent(at0400, RISE, SET)).toEqual({
      event: "sunrise",
      minutesUntil: RISE - at0400,
    });
  });

  it("at sunset exactly → next event is sunrise", () => {
    expect(nextSunEvent(SET, RISE, SET).event).toBe("sunrise");
  });
});

// Symmetric rise/set so the loop midpoints land on exact geometry:
// rise 06:00, set 18:00 → solar noon at 12:00.
const RISE6 = 6 * 60;
const SET18 = 18 * 60;

describe("sunLoopModel — daytime", () => {
  it("solar noon → dot at the arc apex (84, 5), above the horizon", () => {
    const model = sunLoopModel(12 * 60, RISE6, SET18);
    expect(model.phase).toBe("day");
    expect(model.dot).toEqual({ x: 84, y: 5 });
    expect(model.dot.y).toBeLessThan(26);
  });

  it("at sunrise → dot on the left horizon (12, 26)", () => {
    const model = sunLoopModel(RISE6, RISE6, SET18);
    expect(model.dot).toEqual({ x: 12, y: 26 });
  });

  it("at sunset → dot on the right horizon (156, 26), still day phase", () => {
    const model = sunLoopModel(SET18, RISE6, SET18);
    expect(model.phase).toBe("day");
    expect(model.dot).toEqual({ x: 156, y: 26 });
  });

  it("counts down to sunset", () => {
    const model = sunLoopModel(15 * 60, RISE6, SET18);
    expect(model.event).toBe("sunset");
    expect(model.countdownMinutes).toBe(3 * 60);
  });
});

describe("sunLoopModel — nighttime", () => {
  it("night midpoint (midnight for a 6/18 sun) → dot at the dip bottom (84, 39)", () => {
    const model = sunLoopModel(0, RISE6, SET18);
    expect(model.phase).toBe("night");
    expect(model.dot).toEqual({ x: 84, y: 39 });
    expect(model.dot.y).toBeGreaterThan(26);
  });

  it("just after sunset → dot starts the dip on the RIGHT (g≈0 → x near 156)", () => {
    const model = sunLoopModel(SET18 + 1, RISE6, SET18);
    expect(model.phase).toBe("night");
    expect(model.dot.x).toBeGreaterThan(150);
    expect(model.dot.y).toBeGreaterThan(26);
  });

  it("crosses midnight: elapsed wraps, dot moves toward the LEFT before sunrise", () => {
    const model = sunLoopModel(5 * 60, RISE6, SET18); // 05:00, 1h before rise
    expect(model.phase).toBe("night");
    expect(model.dot.x).toBeLessThan(30);
  });

  it("counts down to sunrise across midnight", () => {
    const at2300 = 23 * 60;
    const model = sunLoopModel(at2300, RISE6, SET18);
    expect(model.event).toBe("sunrise");
    expect(model.countdownMinutes).toBe((24 - 23) * 60 + RISE6);
  });

  it("counts down to today's sunrise in the early morning", () => {
    const model = sunLoopModel(4 * 60, RISE6, SET18);
    expect(model.event).toBe("sunrise");
    expect(model.countdownMinutes).toBe(2 * 60);
  });
});

