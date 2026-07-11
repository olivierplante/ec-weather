/**
 * Unit tests for the pure HA version-drift comparison. Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseMinor, minorChanged } from "../lib/version.mjs";

test("parseMinor extracts YYYY.M", () => {
  assert.equal(parseMinor("2026.7.1"), "2026.7");
  assert.equal(parseMinor("2026.12.0b3"), "2026.12");
  assert.equal(parseMinor("v2026.7.1"), "2026.7");
});

test("parseMinor returns null for garbage", () => {
  assert.equal(parseMinor("stable"), null);
  assert.equal(parseMinor(""), null);
});

test("minorChanged is false within the same minor (patch bump)", () => {
  assert.equal(minorChanged("2026.7.1", "2026.7.3"), false);
  assert.equal(minorChanged("2026.7.0", "2026.7.0"), false);
});

test("minorChanged is true across a minor bump", () => {
  assert.equal(minorChanged("2026.7.3", "2026.8.0"), true);
  assert.equal(minorChanged("2026.12.4", "2027.1.0"), true);
});

test("minorChanged treats a missing old value as changed (first run)", () => {
  assert.equal(minorChanged(null, "2026.7.1"), true);
  assert.equal(minorChanged("", "2026.7.1"), true);
});

test("minorChanged throws on an unparseable new tag", () => {
  assert.throws(() => minorChanged("2026.7.1", "not-a-version"), /unparseable/);
});
