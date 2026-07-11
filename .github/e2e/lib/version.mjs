/**
 * HA version-drift comparison (pure). Used by ha-drift.yml to decide whether a
 * newly published home-assistant/core release warrants a full :stable e2e run.
 *
 * The rule (from the test strategy): HA ships breaking changes in MINOR bumps
 * (YYYY.M); patch releases (YYYY.M.p) are bug fixes. So the drift trigger fires
 * only when the MINOR changed — about one run per month.
 *
 * Runnable as a CLI for the workflow:
 *   node lib/version.mjs <old-tag> <new-tag>   -> prints "changed" | "same"
 * and importable for unit tests.
 */

/** Extract the "YYYY.M" minor key from a version tag, or null if unparseable. */
export function parseMinor(tag) {
  const match = String(tag).trim().match(/^v?(\d+)\.(\d+)/);
  if (!match) return null;
  return `${match[1]}.${match[2]}`;
}

/**
 * True when the MINOR (YYYY.M) differs between the two tags. A null/absent old
 * value (no state recorded yet) counts as changed so the first check runs.
 * Throws when the NEW tag is unparseable — a shape change we must not swallow.
 */
export function minorChanged(oldTag, newTag) {
  const next = parseMinor(newTag);
  if (next === null) {
    throw new Error(`unparseable new HA version tag: ${JSON.stringify(newTag)}`);
  }
  const previous = parseMinor(oldTag);
  return previous !== next;
}

// CLI mode: node lib/version.mjs <old> <new>
if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , oldTag, newTag] = process.argv;
  if (!newTag) {
    process.stderr.write("usage: node version.mjs <old-tag> <new-tag>\n");
    process.exit(2);
  }
  process.stdout.write(minorChanged(oldTag, newTag) ? "changed\n" : "same\n");
}
