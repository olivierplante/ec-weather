/**
 * T3 e2e entry point.
 *
 *   node run.mjs <scenario...> [--ha-version <tag|stable>] [--port <n>]
 *
 * Scenarios are given by short id (s1..s5). Standard scenarios (s1-s4) share a
 * single candidate-build container booted here — matching the job grouping in
 * the test strategy (Job A: s1 s2 s3; Job B: s4). s5 manages its own container
 * (Job C) because it starts from the previous release.
 *
 * HA version: "stable" always (latest stable HA is the only supported target —
 * owner decision, July 12, 2026; no version pinning). The --ha-version flag
 * remains ONLY as a local-experimentation override (e.g. reproducing a report
 * against an older image); CI never passes anything but stable.
 *
 * Exit code is non-zero on any scenario failure so the CI job records it.
 */

import { readFile, rm, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { retryOnce } from "./lib/asserts.mjs";
import { dumpContainerDiagnostics } from "./lib/diagnostics.mjs";
import { connect } from "./lib/ws.mjs";
import { onboard } from "./lib/onboarding.mjs";
import {
  installComponent,
  makeConfigDir,
  removeContainer,
  startContainer,
  waitForHttp,
} from "./lib/docker.mjs";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const NEWMARKET = { latitude: 44.056, longitude: -79.462 };

const REGISTRY = {
  s1: "s1-fresh-install.mjs",
  s2: "s2-readd.mjs",
  s3: "s3-rename.mjs",
  s4: "s4-restart.mjs",
  s5: "s5-upgrade.mjs",
};

const log = (message) => process.stdout.write(`[e2e] ${message}\n`);

function parseArgs(argv) {
  const scenarioIds = [];
  // Latest stable is the only supported target; the flag below is a
  // local-experimentation override only.
  let haVersion = "stable";
  let port = 8123;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--ha-version") {
      haVersion = argv[index + 1];
      index += 1;
    } else if (arg === "--port") {
      port = Number(argv[index + 1]);
      index += 1;
    } else if (!arg.startsWith("--")) {
      // Normalize "s1-fresh-install" / "s1.mjs" -> "s1".
      const match = arg.match(/^(s\d+)/i);
      scenarioIds.push(match ? match[1].toLowerCase() : arg.toLowerCase());
    }
  }
  return { scenarioIds, haVersion, port };
}

async function pathExists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

/** Resolve the candidate component dir across both repo layouts. */
async function resolveComponentSource() {
  const up2 = resolve(SCRIPT_DIR, "..", "..");
  const candidates = [join(up2, "custom_components", "ec_weather"), up2];
  for (const candidate of candidates) {
    if (await pathExists(join(candidate, "manifest.json"))) return candidate;
  }
  throw new Error(`could not locate candidate custom_components/ec_weather near ${up2}`);
}

async function loadRequiredRoles() {
  const raw = await readFile(join(SCRIPT_DIR, "required-roles.json"), "utf-8");
  return JSON.parse(raw);
}

async function loadScenario(id) {
  const file = REGISTRY[id];
  if (!file) throw new Error(`unknown scenario id: ${id} (known: ${Object.keys(REGISTRY).join(", ")})`);
  return import(`./scenarios/${file}`);
}

/** Boot a fresh instance with the candidate build and finish onboarding. */
async function bootStandard({ haVersion, componentSource, port }) {
  const configDir = await makeConfigDir();
  await installComponent(configDir, componentSource);
  const container = await startContainer({ haVersion, port, configDir });
  await waitForHttp(container.baseUrl);
  const { accessToken } = await onboard(container.baseUrl);
  const client = await connect(container.baseUrl, accessToken);
  // Best-effort: the config flow searches by city name, so a location set is a
  // nice-to-have (auto-detect default) rather than a hard dependency.
  try {
    await client.updateCoreConfig({
      latitude: NEWMARKET.latitude,
      longitude: NEWMARKET.longitude,
      time_zone: "America/Toronto",
      unit_system: "metric",
    });
  } catch (error) {
    log(`warning: could not set core location (${error.message})`);
  }
  return {
    haVersion,
    componentSource,
    configDir,
    container,
    baseUrl: container.baseUrl,
    token: accessToken,
    client,
    port,
  };
}

async function teardownStandard(ctx) {
  try {
    ctx.client && ctx.client.close();
  } catch {
    /* already closed */
  }
  await removeContainer(ctx.container.name).catch(() => {});
  await rm(ctx.configDir, { recursive: true, force: true }).catch(() => {});
}

async function main() {
  const { scenarioIds, haVersion, port } = parseArgs(process.argv.slice(2));
  if (!scenarioIds.length) {
    process.stderr.write("usage: node run.mjs <scenario...> [--ha-version <tag|stable>]\n");
    process.exit(2);
  }

  const componentSource = await resolveComponentSource();
  const requiredRoles = await loadRequiredRoles();
  const modules = [];
  for (const id of scenarioIds) modules.push(await loadScenario(id));

  log(`HA version: ${haVersion}`);
  log(`scenarios: ${scenarioIds.join(", ")}`);

  const selfBooting = modules.filter((module) => module.managesOwnBoot);
  if (selfBooting.length) {
    if (modules.length !== 1) {
      throw new Error("self-booting scenarios (e.g. s5) must be run alone");
    }
    const module = modules[0];
    const ctx = { haVersion, componentSource, requiredRoles, port, log };
    await runScenario(module, ctx);
    return;
  }

  // Container boot failure retries the whole boot (once).
  const ctx = await retryOnce(
    () => bootStandard({ haVersion, componentSource, port }),
    (error) => log(`retrying container boot after: ${error.message}`),
  );
  ctx.requiredRoles = requiredRoles;
  ctx.log = log;

  try {
    for (const module of modules) {
      log(`=== ${module.id} ===`);
      await runScenario(module, ctx);
    }
  } finally {
    await teardownStandard(ctx);
  }
}

/**
 * Run one scenario (with the retry-once policy); on failure, print the
 * generic container-log diagnostics BEFORE the error propagates, so HTTP
 * statuses from flow exceptions, setup errors, and tracebacks are visible in
 * the CI log (generalizes what S4's restore debugging proved necessary).
 */
async function runScenario(module, ctx) {
  try {
    await retryOnce(() => module.run(ctx), (error) =>
      log(`retrying ${module.id} after: ${error.message}`),
    );
    log(`${module.id} passed`);
  } catch (error) {
    if (ctx.container) {
      await dumpContainerDiagnostics({
        log,
        containerName: ctx.container.name,
        configDir: ctx.configDir || null,
        label: `${module.id} failed: ${error.message}`,
      }).catch(() => {});
    } else {
      log(`no container to dump diagnostics from (${module.id} failed before boot)`);
    }
    throw error;
  }
}

main().catch((error) => {
  process.stderr.write(`[e2e] FAILED: ${error.stack || error.message}\n`);
  process.exit(1);
});
