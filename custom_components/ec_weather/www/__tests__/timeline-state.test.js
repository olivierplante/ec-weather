/**
 * timelineState — tri-state for the daily popup's hourly timeline.
 *
 * EC removed the GDPS-WEonG layers, so days 4-6 come back with zero
 * timesteps. The popup must distinguish "fetched but genuinely empty"
 * (unavailable) from "not fetched yet" (pending), while still preferring
 * the real timeline whenever any timesteps are present.
 */

import { describe, expect, it } from "vitest";

import { timelineState } from "../ec-weather-card.js";

describe("timelineState", () => {
  it("returns 'timeline' when day timesteps are present", () => {
    const item = { timesteps_day: [{ time: "x" }], timesteps_night: [] };
    expect(timelineState(item)).toBe("timeline");
  });

  it("returns 'timeline' when night timesteps are present", () => {
    const item = { timesteps_day: [], timesteps_night: [{ time: "x" }] };
    expect(timelineState(item)).toBe("timeline");
  });

  it("timesteps present wins over an 'unavailable' timesteps_state", () => {
    const item = {
      timesteps_day: [{ time: "x" }],
      timesteps_night: [],
      timesteps_state: "unavailable",
    };
    expect(timelineState(item)).toBe("timeline");
  });

  it("returns 'unavailable' when empty and marked unavailable", () => {
    const item = {
      timesteps_day: [],
      timesteps_night: [],
      timesteps_state: "unavailable",
    };
    expect(timelineState(item)).toBe("unavailable");
  });

  it("returns 'pending' when empty and marked pending", () => {
    const item = {
      timesteps_day: [],
      timesteps_night: [],
      timesteps_state: "pending",
    };
    expect(timelineState(item)).toBe("pending");
  });

  it("returns 'pending' when empty and no timesteps_state", () => {
    const item = { timesteps_day: [], timesteps_night: [] };
    expect(timelineState(item)).toBe("pending");
  });

  it("returns 'pending' when timestep fields are missing entirely", () => {
    expect(timelineState({})).toBe("pending");
  });
});
