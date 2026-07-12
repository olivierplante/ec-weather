/**
 * Unit tests for the pure diagnostics helpers. Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  filterLogLines,
  summarizeMarkers,
  GENERIC_LOG_PATTERN,
} from "../lib/diagnostics.mjs";

const SAMPLE_LOGS = [
  "INFO [homeassistant.core] Starting Home Assistant",
  "WARNING [homeassistant.loader] custom integration ec_weather not tested",
  "ERROR [homeassistant.config_entries] Error setting up entry",
  "Traceback (most recent call last):",
  "INFO [homeassistant.components.http] Now listening",
].join("\n");

test("GENERIC_LOG_PATTERN keeps integration, error and traceback lines", () => {
  const { shown } = filterLogLines(SAMPLE_LOGS, GENERIC_LOG_PATTERN, 200);
  assert.equal(shown.length, 3);
  assert.ok(shown[0].includes("ec_weather"));
  assert.ok(shown[1].includes("Error setting up"));
  assert.ok(shown[2].includes("Traceback"));
});

test("filterLogLines caps the tail and reports the omitted count", () => {
  const logs = Array.from({ length: 10 }, (_, i) => `error line ${i}`).join("\n");
  const { shown, omitted } = filterLogLines(logs, /error/i, 3);
  assert.deepEqual(shown, ["error line 7", "error line 8", "error line 9"]);
  assert.equal(omitted, 7);
});

test("filterLogLines returns zero omitted when under the cap", () => {
  const { shown, omitted } = filterLogLines("error a\nfine\nerror b", /error/, 200);
  assert.deepEqual(shown, ["error a", "error b"]);
  assert.equal(omitted, 0);
});

test("summarizeMarkers reports FOUND/absent per marker", () => {
  const summary = summarizeMarkers(SAMPLE_LOGS, [
    ["setup-error", "Error setting up"],
    ["restored", "restored forecast cache"],
  ]);
  assert.equal(summary, "setup-error=FOUND  restored=absent");
});
