/**
 * Generic config-flow walker for the EC Weather integration.
 *
 * Drives /api/config/config_entries/flow without hard-coding the flow's shape:
 * it inspects each step's serialized data_schema, fills the fields it knows
 * (city search, language), accepts defaults for everything else, and picks the
 * first option for unknown required selects — looping until create_entry (or
 * failing loudly with the full step dump on an unfillable required field).
 *
 * The field-filling logic (`fillStep`, `extractOptions`) and the abort
 * classification (`isAlreadyConfiguredAbort`) are pure and unit-tested; only
 * `walkConfigFlow` / `ensureConfigEntry` touch the network.
 */

import { filterEntriesByDomain, listConfigEntries } from "./rest.mjs";

/**
 * Normalize a serialized schema field's selectable options to
 * `[{ value, label }]`, or null when the field is not a choice.
 *
 * voluptuous-serialize emits options in several shapes depending on whether the
 * field is a bare vol.In, a legacy select, or a SelectSelector:
 *   - field.options: [[value, label], ...] | [{value,label}, ...] | {value: label}
 *   - field.selector.select.options: [{value,label}, ...] | ["value", ...]
 */
export function extractOptions(field) {
  const raw =
    field.options !== undefined
      ? field.options
      : field.selector && field.selector.select
        ? field.selector.select.options
        : undefined;
  if (raw === undefined || raw === null) return null;

  if (Array.isArray(raw)) {
    return raw.map((option) => {
      if (Array.isArray(option)) return { value: option[0], label: String(option[1]) };
      if (option && typeof option === "object") {
        return { value: option.value, label: String(option.label ?? option.value) };
      }
      return { value: option, label: String(option) };
    });
  }
  // Object map { value: label }.
  return Object.entries(raw).map(([value, label]) => ({ value, label: String(label) }));
}

/** True when the field serializes as a plain boolean (checkbox). */
export function isBooleanField(field) {
  if (field.type === "boolean") return true;
  return Boolean(field.selector && field.selector.boolean !== undefined);
}

/**
 * Compute the user_input for one form step.
 *
 * @param {Array<object>} fields  serialized data_schema entries
 * @param {object} known          field-name -> literal value to force
 * @param {object} preferOptionLabel  field-name -> substring; when an unknown
 *   option field matches, that option wins over "first option"
 * @returns {object} the input payload to POST for this step
 * @throws when a required field cannot be filled (error carries `.fields` and
 *   `.unresolved` for a loud dump)
 */
export function fillStep(fields, known = {}, preferOptionLabel = {}) {
  const input = {};
  const unresolved = [];

  for (const field of fields) {
    const name = field.name;
    if (name === undefined) continue;

    if (Object.prototype.hasOwnProperty.call(known, name)) {
      input[name] = known[name];
      continue;
    }

    const options = extractOptions(field);
    if (options && options.length) {
      const wanted = preferOptionLabel[name];
      let chosen;
      if (wanted) {
        chosen = options.find((option) =>
          String(option.label).toLowerCase().includes(String(wanted).toLowerCase()),
        );
      }
      // A default only wins when we have no preferred-label match for it.
      if (!chosen && field.default !== undefined) {
        input[name] = field.default;
        continue;
      }
      input[name] = (chosen ?? options[0]).value;
      continue;
    }

    if (field.default !== undefined) {
      input[name] = field.default;
      continue;
    }

    if (isBooleanField(field)) {
      input[name] = false;
      continue;
    }

    if (field.required) {
      unresolved.push(name);
    }
    // Optional field with no default and no options: omit it.
  }

  if (unresolved.length) {
    const error = new Error(
      `flow-walker: cannot fill required field(s): ${unresolved.join(", ")}`,
    );
    error.fields = fields;
    error.unresolved = unresolved;
    throw error;
  }
  return input;
}

// ---------------------------------------------------------------------------
// Repeated-error-step fail-fast + step-cap diagnostics.
//
// The config flow maps ANY city-search failure to errors={city_query:
// "api_error"} and re-presents the same form; a blind walker re-submits
// immediately up to the step cap — ~40 rapid requests that AMPLIFY the very
// 429/transient that caused the error (ha-drift run 29145482481). Instead:
// an error-step that repeats identically gets a backoff sleep before the
// retry, and three consecutive identical error-steps abort with a message
// naming the repeated error. All decision logic is pure and unit-tested.
// ---------------------------------------------------------------------------

export const MAX_CONSECUTIVE_ERROR_STEPS = 3;
// Sleep before re-submitting a step that just repeated an identical error —
// gives an EC transient / rate limiter room to recover instead of hammering.
export const ERROR_STEP_BACKOFF_MS = 5000;

/** Pure: diagnostic summary of a step — its id, errors dict and field names. */
export function summarizeStep(step) {
  return {
    stepId: step.step_id,
    errors: step.errors || {},
    fieldNames: (step.data_schema || [])
      .map((field) => field.name)
      .filter((name) => name !== undefined),
  };
}

/** Pure: identity key of an ERROR step, or null when the step has no errors. */
function repeatKey(step) {
  const errors = step.errors || {};
  if (!Object.keys(errors).length) return null;
  return JSON.stringify([step.step_id, errors]);
}

/**
 * Pure: fold one step into the consecutive-identical-error counter.
 * `state` is `{ key, count }` (or null at the start); an error-free step
 * resets the count to 0, a different error starts a new sequence at 1.
 */
export function nextRepeatState(state, step) {
  const key = repeatKey(step);
  if (key === null) return { key: null, count: 0 };
  if (state && state.key === key) return { key, count: state.count + 1 };
  return { key, count: 1 };
}

/** Pure: the abort message naming the step and its repeated error. */
export function buildRepeatAbortMessage(step) {
  return (
    `flow-walker: aborting after ${MAX_CONSECUTIVE_ERROR_STEPS} consecutive `
    + `identical error steps on "${step.step_id}" `
    + `(errors: ${JSON.stringify(step.errors || {})})`
  );
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Drive a config-entries flow to completion over REST.
 *
 * @returns the terminal `create_entry` step (has `.result` = entry id).
 * @throws on abort, unknown step type, repeated identical error steps, or
 *   step overrun (the error carries `.lastStep` diagnostics).
 */
export async function walkConfigFlow(
  baseUrl,
  token,
  { handler, known = {}, preferOptionLabel = {}, maxSteps = 20 } = {},
) {
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };

  const postJson = async (url, body) => {
    const response = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
    const text = await response.text();
    let parsed;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`flow-walker: non-JSON response (${response.status}): ${text}`);
    }
    if (!response.ok) {
      throw new Error(`flow-walker: HTTP ${response.status} from ${url}: ${text}`);
    }
    return parsed;
  };

  let step = await postJson(`${baseUrl}/api/config/config_entries/flow`, {
    handler,
    show_advanced_options: false,
  });

  let repeatState = null;
  for (let iteration = 0; iteration < maxSteps; iteration += 1) {
    if (step.type === "create_entry") return step;
    if (step.type === "abort") {
      const error = new Error(`flow-walker: flow aborted (${step.reason})`);
      error.flowAborted = true;
      error.abortReason = step.reason;
      throw error;
    }
    if (step.type === "menu") {
      // Pick the first menu option and continue.
      const options = step.menu_options || [];
      const choice = Array.isArray(options) ? options[0] : Object.keys(options)[0];
      step = await postJson(
        `${baseUrl}/api/config/config_entries/flow/${step.flow_id}`,
        { next_step_id: choice },
      );
      continue;
    }
    if (step.type === "form") {
      repeatState = nextRepeatState(repeatState, step);
      if (repeatState.count >= MAX_CONSECUTIVE_ERROR_STEPS) {
        const error = new Error(buildRepeatAbortMessage(step));
        error.lastStep = summarizeStep(step);
        throw error;
      }
      if (repeatState.count >= 2) {
        // The same error twice in a row: back off before the retry so a
        // rate-limited/transient upstream gets room to recover.
        await sleep(ERROR_STEP_BACKOFF_MS);
      }
      const input = fillStep(step.data_schema || [], known, preferOptionLabel);
      step = await postJson(
        `${baseUrl}/api/config/config_entries/flow/${step.flow_id}`,
        input,
      );
      continue;
    }
    throw new Error(`flow-walker: unexpected step type ${JSON.stringify(step.type)}`);
  }
  // Step overrun: carry evidence — the opaque bare cap message left run
  // 29145482481 undiagnosable.
  const lastStep = summarizeStep(step);
  const error = new Error(
    `flow-walker: flow did not complete within ${maxSteps} steps `
    + `(last step_id=${JSON.stringify(lastStep.stepId)}, `
    + `errors=${JSON.stringify(lastStep.errors)}, `
    + `fields=${JSON.stringify(lastStep.fieldNames)})`,
  );
  error.lastStep = lastStep;
  throw error;
}

/**
 * Pure: true when an error is a flow abort caused by the integration already
 * being configured (the single-instance guard). The retry wrapper re-runs a
 * scenario against the same container, so setup must treat this as benign.
 */
export function isAlreadyConfiguredAbort(error) {
  return Boolean(error && error.flowAborted && error.abortReason === "already_configured");
}

/**
 * Idempotent setup: walk the config flow, but when it aborts with
 * already_configured (a retry re-running setup on the same container), look up
 * the existing entry over REST and continue with it.
 *
 * @returns {{ created: boolean, entryId: string }}
 */
export async function ensureConfigEntry(baseUrl, token, options) {
  try {
    const created = await walkConfigFlow(baseUrl, token, options);
    const entryId = created.result && (created.result.entry_id || created.result);
    return { created: true, entryId };
  } catch (error) {
    if (!isAlreadyConfiguredAbort(error)) throw error;
    const existing = filterEntriesByDomain(
      await listConfigEntries(baseUrl, token),
      options.handler,
    );
    if (!existing.length) {
      throw new Error(
        "flow-walker: flow aborted with already_configured but no "
        + `${options.handler} entry exists`,
      );
    }
    return { created: false, entryId: existing[0].entry_id };
  }
}
