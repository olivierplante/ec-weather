/**
 * S5 — Upgrade path.
 *
 * Boot a container running the PREVIOUS published release, complete a full
 * setup, then swap the component directory to the candidate build (this PR's
 * custom_components/) and restart. After the upgrade: the entry must load with
 * no setup errors, every required role must resolve, and a registry rename must
 * still map to the new id (the contract survives the version bump).
 *
 * Manages its own container lifecycle (Job C), starting from the old release
 * rather than the standard candidate boot.
 */

import { execFile } from "node:child_process";
import { mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

import { assert, pollUntil, rolesCoverRequired } from "../lib/asserts.mjs";
import { ensureConfigEntry } from "../lib/flow-walker.mjs";
import { connect } from "../lib/ws.mjs";
import { onboard } from "../lib/onboarding.mjs";
import {
  installComponent,
  makeConfigDir,
  removeContainer,
  replaceComponentViaDocker,
  restartContainer,
  startContainer,
  waitForHttp,
} from "../lib/docker.mjs";
import { OPTIONAL_ROLES } from "./s1-fresh-install.mjs";

const execFileAsync = promisify(execFile);

const NEWMARKET = { latitude: 44.056, longitude: -79.462 };
const DEFAULT_REPO = "olivierplante/ec-weather";

/**
 * Download the previous published release's custom_components/ec_weather tree
 * into a temp dir and return its path.
 */
async function downloadPreviousRelease(repo, log) {
  const releaseResponse = await fetch(`https://api.github.com/repos/${repo}/releases/latest`, {
    headers: { "User-Agent": "ec-weather-e2e", Accept: "application/vnd.github+json" },
  });
  assert(releaseResponse.ok, `S5: could not read latest release (${releaseResponse.status})`);
  const release = await releaseResponse.json();
  const tag = release.tag_name;
  assert(tag, "S5: latest release has no tag_name");
  log(`S5: previous release is ${tag}`);

  const tarUrl = `https://github.com/${repo}/archive/refs/tags/${tag}.tar.gz`;
  const tarResponse = await fetch(tarUrl, { headers: { "User-Agent": "ec-weather-e2e" } });
  assert(tarResponse.ok, `S5: tarball download failed (${tarResponse.status})`);

  const workDir = await mkdtemp(join(tmpdir(), "ec-e2e-prev-"));
  const tarPath = join(workDir, "release.tar.gz");
  await writeFile(tarPath, Buffer.from(await tarResponse.arrayBuffer()));
  await execFileAsync("tar", ["-xzf", tarPath, "-C", workDir]);

  // Extracted as <repo>-<tag>/... ; find the single top-level dir.
  const entries = await readdir(workDir, { withFileTypes: true });
  const rootDir = entries.find((entry) => entry.isDirectory());
  assert(rootDir, "S5: extracted tarball has no root directory");
  const componentDir = join(workDir, rootDir.name, "custom_components", "ec_weather");
  return componentDir;
}

export const id = "s5";
export const managesOwnBoot = true;

export async function run(ctx) {
  const { haVersion, componentSource, requiredRoles, port = 8123, log } = ctx;
  const repo = process.env.EC_WEATHER_REPO || DEFAULT_REPO;

  const previousComponent = await downloadPreviousRelease(repo, log);

  const configDir = await makeConfigDir();
  await installComponent(configDir, previousComponent);
  const container = await startContainer({ haVersion, port, configDir, name: `ec-e2e-s5-${Date.now()}` });
  ctx.container = container;

  try {
    await waitForHttp(container.baseUrl);
    const { accessToken } = await onboard(container.baseUrl);
    let client = await connect(container.baseUrl, accessToken);
    try {
      await client.updateCoreConfig({
        latitude: NEWMARKET.latitude,
        longitude: NEWMARKET.longitude,
        time_zone: "America/Toronto",
        unit_system: "metric",
      });
    } catch (error) {
      log(`S5 warning: could not set core location (${error.message})`);
    }

    log("S5: full setup on the previous release");
    // Idempotent: a retry re-running S5 setup on the same container hits the
    // single-instance already_configured abort and continues with the entry.
    const created = await ensureConfigEntry(container.baseUrl, accessToken, {
      handler: "ec_weather",
      known: { city_query: "Newmarket", language: "en" },
      preferOptionLabel: { city_id: "Newmarket", city_query: "Newmarket" },
    });
    log(created.created ? "S5: entry created on old release" : "S5: entry already present (retry)");

    await pollUntil(
      async () => {
        const payload = await client.getEcEntities();
        const found = (payload.entries || [])[0];
        return found && found.roles && Object.keys(found.roles).length ? found : null;
      },
      (value) => value !== null,
      { timeoutMs: 90000, intervalMs: 3000 },
    );

    log("S5: swapping in the candidate build (through docker) and restarting");
    client.close();
    // The old release ran as root and littered the bind mount with root-owned
    // __pycache__ — host-side rm would EACCES, so the swap goes through docker.
    await replaceComponentViaDocker(container.name, componentSource);
    await restartContainer(container.name);
    await waitForHttp(container.baseUrl);
    client = await connect(container.baseUrl, accessToken);

    // Entry loads with no setup errors.
    const entries = await client.listConfigEntries("ec_weather");
    const loaded = await pollUntil(
      async () => {
        const current = await client.listConfigEntries("ec_weather");
        const entry = (current || [])[0];
        return entry ? entry.state : null;
      },
      (state) => state === "loaded",
      { timeoutMs: 90000, intervalMs: 3000 },
    );
    assert(loaded.ok, `S5: entry did not reach 'loaded' after upgrade (last: ${loaded.state})`);
    assert(entries.length >= 1, "S5: no ec_weather config entry after upgrade");

    // Roles resolve.
    const payload = await client.getEcEntities();
    const entry = (payload.entries || [])[0];
    assert(entry && entry.roles, "S5: no resolved roles after upgrade");
    const coverage = rolesCoverRequired(entry.roles, requiredRoles, OPTIONAL_ROLES);
    assert(coverage.ok, `S5: roles missing after upgrade: ${coverage.missing.join(", ")}`);
    log(`S5: ${Object.keys(entry.roles).length} roles resolved after upgrade`);

    // Rename still works.
    const originalId = entry.roles.temperature;
    const hostileId = "sensor.upgraded_thermometer_xyz";
    await client.renameEntity(originalId, hostileId);
    const afterRename = await pollUntil(
      async () => {
        const next = await client.getEcEntities();
        const nextEntry = (next.entries || [])[0];
        return nextEntry && nextEntry.roles ? nextEntry.roles.temperature : undefined;
      },
      (resolved) => resolved === hostileId,
      { timeoutMs: 30000, intervalMs: 2000 },
    );
    assert(afterRename.ok, "S5: role did not follow rename after upgrade");
    await client.renameEntity(hostileId, originalId);
    log("S5: rename still maps the role after upgrade");

    client.close();
  } finally {
    await removeContainer(container.name).catch(() => {});
    // Best-effort: the container wrote root-owned files (__pycache__,
    // .storage) into the bind mount; EACCES here must not fail the scenario.
    await rm(configDir, { recursive: true, force: true }).catch(() => {});
  }
}
