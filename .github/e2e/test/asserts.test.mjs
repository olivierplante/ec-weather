/**
 * Unit tests for the pure assertion helpers. Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { isKnownState, rolesCoverRequired, retryOnce } from "../lib/asserts.mjs";

test("isKnownState treats real values as known", () => {
  assert.equal(isKnownState("24.3"), true);
  assert.equal(isKnownState("SW"), true);
  assert.equal(isKnownState("0"), true);
});

test("isKnownState treats unknown/unavailable/empty/null as not known", () => {
  assert.equal(isKnownState("unknown"), false);
  assert.equal(isKnownState("unavailable"), false);
  assert.equal(isKnownState("UNKNOWN"), false);
  assert.equal(isKnownState(""), false);
  assert.equal(isKnownState(null), false);
  assert.equal(isKnownState(undefined), false);
});

test("rolesCoverRequired passes when all required roles resolve", () => {
  const required = {
    temperature: { domain: "sensor", slug: "ec_temperature" },
    condition: { domain: "sensor", slug: "ec_condition" },
  };
  const roles = { temperature: "sensor.ec_temperature", condition: "sensor.ec_condition" };
  assert.deepEqual(rolesCoverRequired(roles, required), { ok: true, missing: [] });
});

test("rolesCoverRequired reports missing roles", () => {
  const required = {
    temperature: { domain: "sensor", slug: "ec_temperature" },
    condition: { domain: "sensor", slug: "ec_condition" },
  };
  const roles = { temperature: "sensor.ec_temperature" };
  const result = rolesCoverRequired(roles, required);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, ["condition"]);
});

test("rolesCoverRequired ignores optional roles when absent", () => {
  const required = {
    temperature: { domain: "sensor", slug: "ec_temperature" },
    yesterday_rain: { domain: "sensor", slug: "ec_yesterday_rain" },
  };
  const roles = { temperature: "sensor.ec_temperature" };
  const result = rolesCoverRequired(roles, required, ["yesterday_rain"]);
  assert.deepEqual(result, { ok: true, missing: [] });
});

test("rolesCoverRequired handles an empty roles map", () => {
  const required = { temperature: { domain: "sensor", slug: "ec_temperature" } };
  const result = rolesCoverRequired(null, required);
  assert.deepEqual(result, { ok: false, missing: ["temperature"] });
});

test("retryOnce returns the first success without retrying", async () => {
  let calls = 0;
  const result = await retryOnce(async () => {
    calls += 1;
    return "ok";
  });
  assert.equal(result, "ok");
  assert.equal(calls, 1);
});

test("retryOnce retries once on the first failure and then succeeds", async () => {
  let calls = 0;
  const result = await retryOnce(async () => {
    calls += 1;
    if (calls === 1) throw new Error("transient");
    return "recovered";
  });
  assert.equal(result, "recovered");
  assert.equal(calls, 2);
});

test("retryOnce re-throws the second failure, carrying the first", async () => {
  let calls = 0;
  await assert.rejects(
    () =>
      retryOnce(async () => {
        calls += 1;
        throw new Error(`fail-${calls}`);
      }),
    (error) => {
      assert.equal(error.message, "fail-2");
      assert.equal(error.firstAttemptError.message, "fail-1");
      return true;
    },
  );
  assert.equal(calls, 2);
});
