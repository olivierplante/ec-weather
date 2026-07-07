/**
 * staleInfo() — the stale-banner decision (review finding: keying off
 * last_updated alone flags stable-but-fresh readings as outdated, because
 * HA only writes a new state object when the value changes).
 *
 * The integration stamps attributes.fetched_at on every successful fetch;
 * the card measures staleness from that heartbeat and only falls back to
 * last_updated for servers running an older integration build.
 */

import { describe, expect, it } from "vitest";

import { staleInfo } from "../ec-weather-card.js";

const NOW = Date.parse("2026-07-04T18:00:00Z");
const hoursAgo = (hours) => new Date(NOW - hours * 3600000).toISOString();

describe("staleInfo", () => {
  it("fresh heartbeat + old last_updated → NOT stale (the false-positive case)", () => {
    const state = {
      attributes: { fetched_at: hoursAgo(0.5) },
      last_updated: hoursAgo(5),
    };
    expect(staleInfo(state, NOW)).toBeNull();
  });

  it("old heartbeat → stale with rounded hours", () => {
    const state = {
      attributes: { fetched_at: hoursAgo(3.2) },
      last_updated: hoursAgo(0.1),
    };
    expect(staleInfo(state, NOW)).toEqual({ agoHours: 3 });
  });

  it("no heartbeat attribute → falls back to last_updated (older integration)", () => {
    expect(staleInfo({ attributes: {}, last_updated: hoursAgo(4) }, NOW))
      .toEqual({ agoHours: 4 });
    expect(staleInfo({ attributes: {}, last_updated: hoursAgo(1) }, NOW)).toBeNull();
  });

  it("threshold is 2 hours", () => {
    const at = (hours) => staleInfo({ attributes: { fetched_at: hoursAgo(hours) } }, NOW);
    expect(at(1.9)).toBeNull();
    expect(at(2.1)).not.toBeNull();
  });

  it("missing state or timestamps → no banner, no crash", () => {
    expect(staleInfo(null, NOW)).toBeNull();
    expect(staleInfo({ attributes: {} }, NOW)).toBeNull();
    expect(staleInfo({ attributes: { fetched_at: "garbage" } }, NOW)).toBeNull();
  });
});
