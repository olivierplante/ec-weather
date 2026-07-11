/**
 * Assertion helpers for the e2e scenarios.
 *
 * Assertion discipline (from the test strategy): deterministic behaviour (HA
 * registry, our code) is asserted strictly; EC-network-backed data leniently
 * (exists / leaves-unknown within a timeout). The pure predicates here
 * (`isKnownState`, `rolesCoverRequired`) are unit-tested; the polling/retry
 * wrappers are exercised in CI.
 */

/** An HA state string that represents "no real value yet". */
const NON_VALUES = new Set(["unknown", "unavailable", "", "none"]);

/** True when a state string is a real, settled value (not unknown/unavailable). */
export function isKnownState(state) {
  if (state === null || state === undefined) return false;
  return !NON_VALUES.has(String(state).trim().toLowerCase());
}

/**
 * Check that a resolved-roles map covers every required role.
 *
 * @param {object} roles     role -> entity_id (from ec_weather/entities)
 * @param {object} required  the required-roles.json contract (role -> {domain, slug})
 * @param {string[]} [optional]  roles allowed to be absent (e.g. precip sensors
 *   that only exist when a station is configured)
 * @returns {{ ok: boolean, missing: string[] }}
 */
export function rolesCoverRequired(roles, required, optional = []) {
  const skip = new Set(optional);
  const missing = Object.keys(required)
    .filter((role) => !skip.has(role))
    .filter((role) => !roles || !roles[role]);
  return { ok: missing.length === 0, missing };
}

/** Assert helper that throws a labelled Error when the condition is falsy. */
export function assert(condition, message) {
  if (!condition) throw new Error(`assertion failed: ${message}`);
}

/** Sleep for the given milliseconds. */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Poll an entity's state until `predicate(state)` holds or the timeout elapses.
 *
 * @param {() => Promise<string|null>} readState  fetches the current state
 * @param {(state: string|null) => boolean} predicate
 * @param {{ timeoutMs?: number, intervalMs?: number }} [opts]
 * @returns {Promise<{ ok: boolean, state: string|null, waitedMs: number }>}
 */
export async function pollUntil(readState, predicate, { timeoutMs = 90000, intervalMs = 3000 } = {}) {
  const started = Date.now();
  let state = null;
  while (Date.now() - started < timeoutMs) {
    state = await readState();
    if (predicate(state)) {
      return { ok: true, state, waitedMs: Date.now() - started };
    }
    await sleep(intervalMs);
  }
  return { ok: false, state, waitedMs: Date.now() - started };
}

/**
 * Run an async task, retrying it exactly once if the first attempt throws.
 * Returns the task result; re-throws the second failure (with both causes).
 */
export async function retryOnce(task, onRetry) {
  try {
    return await task();
  } catch (firstError) {
    if (onRetry) await onRetry(firstError);
    try {
      return await task();
    } catch (secondError) {
      secondError.firstAttemptError = firstError;
      throw secondError;
    }
  }
}
