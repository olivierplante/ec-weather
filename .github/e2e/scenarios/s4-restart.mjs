/**
 * S4 — Restart persistence (the persistent forecast cache).
 *
 * Fresh install, let WEonG fetch and persist, then restart the container. After
 * the reboot: the cache-restore log line must be present, and the forecast
 * attributes must repopulate shortly after boot. No timing/count assertions —
 * only that restore happened and data came back.
 *
 * The persist happens only AFTER a successful GeoMet wave (Store key
 * "ec_weather.<entry_id>", debounced 5s — see const.py STORAGE_SAVE_DELAY and
 * coordinator/weong.py). A fixed sleep races it, so the pre-restart wait is
 * deterministic: poll the host-mounted config dir for the store file under
 * .storage/. Per the assertion discipline, GeoMet-backed data is asserted
 * leniently — if the store never persists within the timeout (GeoMet slow or
 * down), S4 SKIPS loudly instead of failing the gate on GeoMet weather.
 *
 * Runs alone in its own container (Job B).
 */

import { readdir } from "node:fs/promises";
import { join } from "node:path";

import { assert, pollUntil, sleep, isKnownState } from "../lib/asserts.mjs";
import { ensureConfigEntry } from "../lib/flow-walker.mjs";
import { connect } from "../lib/ws.mjs";
import { containerLogs, restartContainer, waitForHttp } from "../lib/docker.mjs";

// Substring of the INFO line coordinator/weong.py logs on cache restore:
// "EC WEonG: restored forecast cache — ...".
const RESTORE_LOG_MARKER = "restored forecast cache";
// Mirrors const.py STORAGE_SAVE_DELAY (5s async_delay_save debounce): once the
// store file exists, one debounce-sized beat lets the final write settle.
const STORAGE_SAVE_DELAY_MS = 5000;

/**
 * Pure: true when a .storage entry is the integration's persistent forecast
 * cache. coordinator/weong.py: Store(hass, STORAGE_VERSION,
 * f"{DOMAIN}.{entry_id}") -> file ".storage/ec_weather.<entry_id>".
 */
export function isComponentStoreFile(fileName) {
  return fileName.startsWith("ec_weather.");
}

/**
 * Poll the host-mounted config dir until the WEonG store file exists.
 * Existence only (fs stat via readdir) — the file itself is root-owned 0600,
 * but listing the directory is enough and needs no read access to the file.
 *
 * @returns {Promise<boolean>} true when the store file appeared in time
 */
async function waitForStoreFile(configDir, { timeoutMs = 120000, intervalMs = 3000 } = {}) {
  const storageDir = join(configDir, ".storage");
  const result = await pollUntil(
    async () => {
      const entries = await readdir(storageDir).catch(() => []);
      return entries.some(isComponentStoreFile) ? "present" : null;
    },
    (value) => value === "present",
    { timeoutMs, intervalMs },
  );
  return result.ok;
}

async function waitForForecast(client, entityId, timeoutMs) {
  return pollUntil(
    async () => {
      const stateObject = await client.getStateObject(entityId);
      const forecast = stateObject && stateObject.attributes && stateObject.attributes.forecast;
      return Array.isArray(forecast) && forecast.length ? "populated" : null;
    },
    (value) => value === "populated",
    { timeoutMs, intervalMs: 4000 },
  );
}

export const id = "s4";

export async function run(ctx) {
  const { baseUrl, token, log } = ctx;
  let client = ctx.client;

  log("S4: fresh install before restart");
  // Idempotent: a retry re-running S4 on the same container hits the
  // single-instance already_configured abort and continues with the entry.
  const created = await ensureConfigEntry(baseUrl, token, {
    handler: "ec_weather",
    known: { city_query: "Newmarket", language: "en" },
    preferOptionLabel: { city_id: "Newmarket", city_query: "Newmarket" },
  });
  log(created.created ? "S4: entry created" : "S4: entry already present (retry)");

  // Wait until the daily forecast is populated (proves WEonG fetched).
  const entry = await pollUntil(
    async () => {
      const payload = await client.getEcEntities();
      const found = (payload.entries || [])[0];
      return found && found.roles && found.roles.daily_forecast ? found : null;
    },
    (value) => value !== null,
    { timeoutMs: 90000, intervalMs: 3000 },
  );
  assert(entry.ok, "S4: no loaded entry with a daily_forecast role before restart");
  const dailyId = entry.state.roles.daily_forecast;

  const populated = await waitForForecast(client, dailyId, 120000);
  assert(populated.ok, "S4: daily forecast never populated before restart");

  // Deterministic persist wait: the store file only appears after a successful
  // GeoMet wave. Lenient by discipline — skip, never fail, on GeoMet weather.
  log("S4: waiting for the WEonG store file to persist (<= 120s)");
  const persisted = await waitForStoreFile(ctx.configDir, { timeoutMs: 120000 });
  if (!persisted) {
    log("==================================================================");
    log("S4 SKIPPED: WEonG store never persisted (GeoMet slow or down)");
    log("==================================================================");
    return;
  }
  // One debounce-sized beat so the write that created the file settles.
  await sleep(STORAGE_SAVE_DELAY_MS);
  log("S4: store file present");

  log("S4: restarting the container");
  client.close();
  await restartContainer(ctx.container.name);
  await waitForHttp(baseUrl);
  client = await connect(baseUrl, token);
  ctx.client = client;

  // Cache-restore log line present. Boot race: waitForHttp returns when HA's
  // API answers, but integrations set up AFTER that — the restore line is
  // emitted during ec_weather's async_setup_entry, which can lag the API by
  // tens of seconds. Poll the logs instead of reading them once.
  const restoreLogged = await pollUntil(
    () => containerLogs(ctx.container.name),
    (logs) => typeof logs === "string" && logs.includes(RESTORE_LOG_MARKER),
    { timeoutMs: 90000, intervalMs: 3000 },
  );
  assert(
    restoreLogged.ok,
    `S4: cache-restore log line ("${RESTORE_LOG_MARKER}") not found within 90s of restart`,
  );
  log("S4: cache-restore log line present");

  // Forecast attributes repopulate shortly after boot. Same boot race applies;
  // waitForForecast already polls generously (120s, tolerating the entity
  // being absent until setup finishes), so it rides out integration startup.
  const afterBoot = await waitForForecast(client, dailyId, 120000);
  assert(afterBoot.ok, "S4: daily forecast did not repopulate after restart");

  const tempResult = await pollUntil(
    async () => {
      const payload = await client.getEcEntities();
      const found = (payload.entries || [])[0];
      const tempId = found && found.roles && found.roles.temperature;
      return tempId ? client.getState(tempId) : null;
    },
    (state) => isKnownState(state),
    { timeoutMs: 90000, intervalMs: 3000 },
  );
  assert(tempResult.ok, "S4: temperature did not settle after restart");
  log("S4: forecast and temperature back after restart");
}
