/**
 * Shared failure diagnostics: a delimited, filtered container-log dump.
 *
 * Grown out of S4's restore-path debugging (which proved that a failing CI
 * run must SHOW the relevant container logs, not leave us guessing) and
 * generalized so run.mjs can dump on ANY scenario failure — HTTP statuses
 * from flow exceptions, tracebacks, setup errors all become visible.
 *
 * The line filtering and marker summary are pure (unit-tested); only
 * `dumpContainerDiagnostics` touches docker/fs, and it NEVER throws — it is
 * evidence printing, not control flow.
 */

import { readdir } from "node:fs/promises";
import { join } from "node:path";

import { containerLogs } from "./docker.mjs";

// Generic scenario-failure filter: integration lines plus anything error- or
// traceback-shaped from any logger.
export const GENERIC_LOG_PATTERN = /ec_weather|EC WEonG|error|traceback/i;
export const GENERIC_MAX_LINES = 200;

/**
 * Pure: keep the log lines matching `pattern`, tail-capped at `maxLines`
 * (the most recent output is the interesting part).
 *
 * @returns {{ shown: string[], omitted: number }}
 */
export function filterLogLines(logs, pattern, maxLines) {
  const matching = String(logs).split("\n").filter((line) => pattern.test(line));
  const shown = matching.slice(-maxLines);
  return { shown, omitted: matching.length - shown.length };
}

/**
 * Pure: one-line FOUND/absent summary for a list of [name, substring] markers.
 */
export function summarizeMarkers(logs, markers) {
  return markers
    .map(([name, marker]) => `${name}=${String(logs).includes(marker) ? "FOUND" : "absent"}`)
    .join("  ");
}

/**
 * Print a clearly-delimited diagnostic dump for a container.
 *
 * @param {object} options
 * @param {(message: string) => void} options.log
 * @param {string} options.containerName
 * @param {string} options.label       what failed (shown in the delimiter)
 * @param {RegExp} [options.pattern]   line filter (default: generic)
 * @param {number} [options.maxLines]  tail cap (default: 200)
 * @param {Array<[string, string]>} [options.markers]  optional marker summary
 * @param {string|null} [options.configDir]  when set, also list .storage names
 */
export async function dumpContainerDiagnostics({
  log,
  containerName,
  label,
  pattern = GENERIC_LOG_PATTERN,
  maxLines = GENERIC_MAX_LINES,
  markers = [],
  configDir = null,
}) {
  log(`========== DIAGNOSTICS: ${label} ==========`);
  let logs = "";
  try {
    logs = await containerLogs(containerName);
  } catch (error) {
    log(`diagnostics: could not read container logs (${error.message})`);
  }

  const { shown, omitted } = filterLogLines(logs, pattern, maxLines);
  if (omitted > 0) {
    log(`diagnostics: ${omitted} earlier matching line(s) omitted (cap ${maxLines})`);
  }
  for (const line of shown) log(`| ${line}`);

  if (markers.length) {
    log(`marker summary: ${summarizeMarkers(logs, markers)}`);
  }

  if (configDir) {
    const storageEntries = await readdir(join(configDir, ".storage"))
      .catch((error) => [`<unreadable: ${error.message}>`]);
    log(`.storage listing: ${storageEntries.join(", ") || "<empty>"}`);
  }
  log(`========== END DIAGNOSTICS ==========`);
}
