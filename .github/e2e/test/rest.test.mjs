/**
 * Unit tests for the pure REST helpers and the S4 store-file predicate.
 * Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { filterEntriesByDomain } from "../lib/rest.mjs";
import { isComponentStoreFile } from "../scenarios/s4-restart.mjs";

test("filterEntriesByDomain keeps only the requested domain", () => {
  const entries = [
    { entry_id: "aaa", domain: "ec_weather" },
    { entry_id: "bbb", domain: "sun" },
    { entry_id: "ccc", domain: "ec_weather" },
  ];
  const filtered = filterEntriesByDomain(entries, "ec_weather");
  assert.deepEqual(filtered.map((entry) => entry.entry_id), ["aaa", "ccc"]);
});

test("filterEntriesByDomain returns [] when nothing matches", () => {
  assert.deepEqual(filterEntriesByDomain([{ domain: "sun" }], "ec_weather"), []);
});

test("filterEntriesByDomain tolerates null / malformed lists", () => {
  assert.deepEqual(filterEntriesByDomain(null, "ec_weather"), []);
  assert.deepEqual(filterEntriesByDomain(undefined, "ec_weather"), []);
  assert.deepEqual(filterEntriesByDomain([null, {}], "ec_weather"), []);
});

test("isComponentStoreFile matches the WEonG store key (ec_weather.<entry_id>)", () => {
  assert.equal(isComponentStoreFile("ec_weather.01KXABCDEF0123456789ABCDEF"), true);
});

test("isComponentStoreFile rejects other .storage files", () => {
  assert.equal(isComponentStoreFile("core.config_entries"), false);
  assert.equal(isComponentStoreFile("core.entity_registry"), false);
  assert.equal(isComponentStoreFile("http.auth"), false);
  // Prefix must be the full "ec_weather." key, dot included.
  assert.equal(isComponentStoreFile("ec_weather_something_else"), false);
});
