/**
 * Unit tests for the pure S5 release-fetch header builder. Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { releaseFetchHeaders } from "../scenarios/s5-upgrade.mjs";

test("releaseFetchHeaders adds a Bearer Authorization header when GITHUB_TOKEN is set", () => {
  const headers = releaseFetchHeaders({ GITHUB_TOKEN: "gh-token-abc123" });
  assert.deepEqual(headers, {
    "User-Agent": "ec-weather-e2e",
    Accept: "application/vnd.github+json",
    Authorization: "Bearer gh-token-abc123",
  });
});

test("releaseFetchHeaders omits Authorization when GITHUB_TOKEN is unset", () => {
  const headers = releaseFetchHeaders({});
  assert.deepEqual(headers, {
    "User-Agent": "ec-weather-e2e",
    Accept: "application/vnd.github+json",
  });
  assert.equal("Authorization" in headers, false);
});

test("releaseFetchHeaders omits Authorization when GITHUB_TOKEN is an empty string", () => {
  const headers = releaseFetchHeaders({ GITHUB_TOKEN: "" });
  assert.equal("Authorization" in headers, false);
});
