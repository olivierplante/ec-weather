/**
 * S2 — Delete entry + re-add, NO restart.
 *
 * Real registry transition that the deleted-entity-restore bug lived in:
 * removing the config entry then re-adding it (in the SAME running instance)
 * must re-resolve every required role, and temperature must recover within 90s.
 * Ids may differ from the first install — the card reads by role, so we assert
 * roles resolve, not specific ids.
 *
 * Runs after S1 in the same container (one install's natural lifecycle).
 */

import { assert, pollUntil, rolesCoverRequired, isKnownState } from "../lib/asserts.mjs";
import { walkConfigFlow } from "../lib/flow-walker.mjs";
import { OPTIONAL_ROLES } from "./s1-fresh-install.mjs";

async function waitForLoadedEntry(client, timeoutMs = 90000) {
  const result = await pollUntil(
    async () => {
      const payload = await client.getEcEntities();
      const entry = (payload.entries || [])[0];
      return entry && entry.roles && Object.keys(entry.roles).length ? entry : null;
    },
    (entry) => entry !== null,
    { timeoutMs, intervalMs: 3000 },
  );
  assert(result.ok, `no loaded ec_weather entry with roles within ${timeoutMs}ms`);
  return result.state;
}

export const id = "s2";

export async function run(ctx) {
  const { client, baseUrl, token, requiredRoles, log } = ctx;

  // Find the current entry (from S1, or discover it fresh).
  let entryId = ctx.entryId;
  if (!entryId) {
    const payload = await client.getEcEntities();
    entryId = payload.entries && payload.entries[0] && payload.entries[0].entry_id;
  }
  assert(entryId, "S2: no existing config entry to remove");

  log(`S2: removing config entry ${entryId}`);
  await client.removeConfigEntry(entryId);

  // Confirm it is gone before re-adding.
  const removed = await pollUntil(
    async () => {
      const payload = await client.getEcEntities();
      return (payload.entries || []).length;
    },
    (count) => count === 0,
    { timeoutMs: 30000, intervalMs: 2000 },
  );
  assert(removed.ok, "S2: config entry did not disappear after removal");

  log("S2: re-adding the integration (no restart)");
  const created = await walkConfigFlow(baseUrl, token, {
    handler: "ec_weather",
    known: { city_query: "Newmarket", language: "en" },
    preferOptionLabel: { city_id: "Newmarket", city_query: "Newmarket" },
  });
  assert(created.type === "create_entry", `expected create_entry, got ${created.type}`);
  ctx.entryId = created.result && (created.result.entry_id || created.result);

  const entry = await waitForLoadedEntry(client);
  const coverage = rolesCoverRequired(entry.roles, requiredRoles, OPTIONAL_ROLES);
  assert(coverage.ok, `S2: roles did not re-resolve: missing ${coverage.missing.join(", ")}`);
  log(`S2: ${Object.keys(entry.roles).length} roles re-resolved`);

  const tempResult = await pollUntil(
    () => client.getState(entry.roles.temperature),
    (state) => isKnownState(state),
    { timeoutMs: 90000, intervalMs: 3000 },
  );
  assert(tempResult.ok, `S2: temperature did not recover within 90s (last: ${tempResult.state})`);
  log(`S2: temperature recovered to ${tempResult.state}`);
}
