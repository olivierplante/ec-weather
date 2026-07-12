/**
 * Unit tests for the pure flow-walker field-filling logic. Runs without docker:
 *   node --test .github/e2e/test/
 *
 * The step payloads below mirror the real serialized data_schema shapes from
 * config_flow.py (user, select_city, confirm, precip steps).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  extractOptions,
  isBooleanField,
  fillStep,
  isAlreadyConfiguredAbort,
  summarizeStep,
  nextRepeatState,
  buildRepeatAbortMessage,
  MAX_CONSECUTIVE_ERROR_STEPS,
} from "../lib/flow-walker.mjs";

test("extractOptions normalizes [value,label] pairs", () => {
  const field = { name: "language", options: [["en", "English"], ["fr", "Français"]] };
  assert.deepEqual(extractOptions(field), [
    { value: "en", label: "English" },
    { value: "fr", label: "Français" },
  ]);
});

test("extractOptions normalizes a SelectSelector's option objects", () => {
  const field = {
    name: "city_id",
    selector: { select: { options: [
      { value: "on-118", label: "Ottawa (ON)" },
      { value: "on-124", label: "Newmarket (ON)" },
    ] } },
  };
  assert.deepEqual(extractOptions(field), [
    { value: "on-118", label: "Ottawa (ON)" },
    { value: "on-124", label: "Newmarket (ON)" },
  ]);
});

test("extractOptions returns null for non-choice fields", () => {
  assert.equal(extractOptions({ name: "lat", type: "float" }), null);
});

test("isBooleanField detects boolean type and boolean selector", () => {
  assert.equal(isBooleanField({ name: "x", type: "boolean" }), true);
  assert.equal(isBooleanField({ name: "y", selector: { boolean: {} } }), true);
  assert.equal(isBooleanField({ name: "z", type: "string" }), false);
});

test("fillStep fills known fields (user step: city_query + language)", () => {
  const fields = [
    { name: "city_query", required: true, type: "string" },
    { name: "language", required: true, options: [["en", "English"], ["fr", "Français"]], default: "en" },
  ];
  const input = fillStep(fields, { city_query: "Newmarket", language: "en" });
  assert.deepEqual(input, { city_query: "Newmarket", language: "en" });
});

test("fillStep accepts defaults on the confirm step", () => {
  const fields = [
    { name: "lat", required: true, type: "float", default: 44.056 },
    { name: "lon", required: true, type: "float", default: -79.462 },
    { name: "bbox", required: true, type: "string", default: "-79.7,43.9,-79.3,44.3" },
    { name: "geomet_bbox", required: true, type: "string", default: "43.056,-80.462,45.056,-78.462" },
    { name: "aqhi_location_id", required: false, type: "string", default: "" },
  ];
  const input = fillStep(fields, {});
  assert.equal(input.lat, 44.056);
  assert.equal(input.lon, -79.462);
  assert.equal(input.bbox, "-79.7,43.9,-79.3,44.3");
  assert.equal(input.aqhi_location_id, "");
});

test("fillStep uses the default for the precip opt-out select", () => {
  const fields = [
    {
      name: "precip_station_id",
      required: true,
      default: "__none__",
      selector: { select: { options: [
        { value: "6104175", label: "Toronto — 12 km — rain & snow" },
        { value: "__none__", label: "Don't add yesterday's precipitation" },
      ] } },
    },
  ];
  const input = fillStep(fields, {});
  assert.equal(input.precip_station_id, "__none__");
});

test("fillStep prefers an option by label over the first option (disambiguation)", () => {
  const fields = [
    {
      name: "city_id",
      required: true,
      selector: { select: { options: [
        { value: "on-118", label: "Ottawa (ON)" },
        { value: "on-124", label: "Newmarket (ON)" },
      ] } },
    },
  ];
  const input = fillStep(fields, {}, { city_id: "Newmarket" });
  assert.equal(input.city_id, "on-124");
});

test("fillStep falls back to the first option for an unknown required select", () => {
  const fields = [
    { name: "city_id", required: true, options: [["a", "Alpha"], ["b", "Beta"]] },
  ];
  const input = fillStep(fields, {});
  assert.equal(input.city_id, "a");
});

test("fillStep defaults a checkbox to false", () => {
  const fields = [{ name: "extended_forecast", required: false, type: "boolean" }];
  assert.deepEqual(fillStep(fields, {}), { extended_forecast: false });
});

test("fillStep omits an optional text field with no default", () => {
  const fields = [{ name: "aqhi_location_id", required: false, type: "string" }];
  assert.deepEqual(fillStep(fields, {}), {});
});

test("fillStep throws with a dump on an unfillable required field", () => {
  const fields = [{ name: "mystery", required: true, type: "string" }];
  assert.throws(
    () => fillStep(fields, {}),
    (error) => {
      assert.match(error.message, /mystery/);
      assert.deepEqual(error.unresolved, ["mystery"]);
      assert.equal(error.fields, fields);
      return true;
    },
  );
});

// ---------------------------------------------------------------------------
// Abort classification (idempotent-setup path: a retry re-running setup on the
// same container hits the single-instance already_configured abort)
// ---------------------------------------------------------------------------

function abortError(reason) {
  const error = new Error(`flow-walker: flow aborted (${reason})`);
  error.flowAborted = true;
  error.abortReason = reason;
  return error;
}

test("isAlreadyConfiguredAbort matches an already_configured flow abort", () => {
  assert.equal(isAlreadyConfiguredAbort(abortError("already_configured")), true);
});

test("isAlreadyConfiguredAbort rejects other abort reasons", () => {
  assert.equal(isAlreadyConfiguredAbort(abortError("no_city_found")), false);
  assert.equal(isAlreadyConfiguredAbort(abortError("api_error")), false);
});

test("isAlreadyConfiguredAbort rejects non-abort errors", () => {
  assert.equal(isAlreadyConfiguredAbort(new Error("already_configured")), false);
  assert.equal(isAlreadyConfiguredAbort(new Error("HTTP 500")), false);
  assert.equal(isAlreadyConfiguredAbort(null), false);
  assert.equal(isAlreadyConfiguredAbort(undefined), false);
});

// ---------------------------------------------------------------------------
// Step-cap diagnostics + repeated-error-step fail-fast (ha-drift run
// 29145482481: an EC transient/429 on the city search made the walker
// re-submit ~40 times to the 20-step cap with an opaque error).
// ---------------------------------------------------------------------------

const apiErrorStep = () => ({
  type: "form",
  step_id: "user",
  errors: { city_query: "api_error" },
  data_schema: [
    { name: "city_query", required: true, type: "string" },
    { name: "language", required: true, options: [["en", "English"]], default: "en" },
  ],
});

test("summarizeStep extracts step_id, errors and schema field names", () => {
  const summary = summarizeStep(apiErrorStep());
  assert.equal(summary.stepId, "user");
  assert.deepEqual(summary.errors, { city_query: "api_error" });
  assert.deepEqual(summary.fieldNames, ["city_query", "language"]);
});

test("summarizeStep tolerates a step with no errors and no schema", () => {
  const summary = summarizeStep({ type: "form", step_id: "confirm" });
  assert.equal(summary.stepId, "confirm");
  assert.deepEqual(summary.errors, {});
  assert.deepEqual(summary.fieldNames, []);
});

test("nextRepeatState counts consecutive identical error steps", () => {
  let state = nextRepeatState(null, apiErrorStep());
  assert.equal(state.count, 1);
  state = nextRepeatState(state, apiErrorStep());
  assert.equal(state.count, 2);
  state = nextRepeatState(state, apiErrorStep());
  assert.equal(state.count, 3);
});

test("nextRepeatState resets on a DIFFERENT step (id or errors)", () => {
  let state = nextRepeatState(null, apiErrorStep());
  state = nextRepeatState(state, apiErrorStep());
  assert.equal(state.count, 2);
  // Different errors on the same step -> new sequence.
  state = nextRepeatState(state, {
    type: "form", step_id: "user", errors: { city_query: "no_city_found" }, data_schema: [],
  });
  assert.equal(state.count, 1);
  // Different step_id, same errors -> new sequence too.
  state = nextRepeatState(state, {
    type: "form", step_id: "confirm", errors: { city_query: "no_city_found" }, data_schema: [],
  });
  assert.equal(state.count, 1);
});

test("nextRepeatState resets to zero on an error-free step", () => {
  let state = nextRepeatState(null, apiErrorStep());
  state = nextRepeatState(state, { type: "form", step_id: "user", errors: {}, data_schema: [] });
  assert.equal(state.count, 0);
  // A fresh error afterwards starts at 1 again.
  state = nextRepeatState(state, apiErrorStep());
  assert.equal(state.count, 1);
});

test("MAX_CONSECUTIVE_ERROR_STEPS is 3 (abort threshold)", () => {
  assert.equal(MAX_CONSECUTIVE_ERROR_STEPS, 3);
});

test("buildRepeatAbortMessage names the step and the repeated error", () => {
  const message = buildRepeatAbortMessage(apiErrorStep());
  assert.match(message, /3 consecutive identical error steps/);
  assert.match(message, /"user"/);
  assert.match(message, /city_query/);
  assert.match(message, /api_error/);
});
