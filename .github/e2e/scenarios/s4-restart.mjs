/**
 * S4 — Restart persistence (the persistent forecast cache).
 *
 * Fresh install, let WEonG fetch and persist, then restart the container. After
 * the reboot: the cache-restore log line must be present, and the forecast
 * attributes must repopulate shortly after boot. No timing/count assertions —
 * only that restore happened and data came back.
 *
 * Runs alone in its own container (Job B).
 */

import { assert, pollUntil, sleep, isKnownState } from "../lib/asserts.mjs";
import { walkConfigFlow } from "../lib/flow-walker.mjs";
import { connect } from "../lib/ws.mjs";
import { containerLogs, restartContainer, waitForHttp } from "../lib/docker.mjs";

// Substring of the INFO line coordinator/weong.py logs on cache restore:
// "EC WEonG: restored forecast cache — ...".
const RESTORE_LOG_MARKER = "restored forecast cache";
// Mirrors const.py STORAGE_SAVE_DELAY (5s async_delay_save debounce).
const STORAGE_SAVE_DELAY_MS = 5000;

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
  const created = await walkConfigFlow(baseUrl, token, {
    handler: "ec_weather",
    known: { city_query: "Newmarket", language: "en" },
    preferOptionLabel: { city_id: "Newmarket", city_query: "Newmarket" },
  });
  assert(created.type === "create_entry", `expected create_entry, got ${created.type}`);

  // Wait until the daily forecast is populated (proves WEonG fetched), then a
  // beat longer than the persist debounce so the cache file is written.
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
  log("S4: forecast populated; waiting out the persist debounce");
  await sleep(STORAGE_SAVE_DELAY_MS + 10000);

  log("S4: restarting the container");
  client.close();
  await restartContainer(ctx.container.name);
  await waitForHttp(baseUrl);
  client = await connect(baseUrl, token);
  ctx.client = client;

  // Cache-restore log line present.
  const logs = await containerLogs(ctx.container.name);
  assert(
    logs.includes(RESTORE_LOG_MARKER),
    `S4: cache-restore log line ("${RESTORE_LOG_MARKER}") not found after restart`,
  );
  log("S4: cache-restore log line present");

  // Forecast attributes repopulate shortly after boot.
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
