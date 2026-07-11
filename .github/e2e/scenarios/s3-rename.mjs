/**
 * S3 — Rename hostility (the whole point of the role contract).
 *
 * Rename the temperature sensor via the entity-registry WS API to a hostile
 * custom id, then confirm ec_weather/entities maps the `temperature` role to
 * that NEW id (resolution is by unique_id, immune to user renames — issue #12).
 * Rename it back and confirm the role follows again.
 *
 * Runs after S2 in the same container.
 */

import { assert, pollUntil } from "../lib/asserts.mjs";

async function resolveRole(client, role) {
  const payload = await client.getEcEntities();
  const entry = (payload.entries || [])[0];
  return entry && entry.roles ? entry.roles[role] : undefined;
}

/** Poll ec_weather/entities until the role resolves to `expectedId`. */
async function waitForRole(client, role, expectedId, timeoutMs = 30000) {
  return pollUntil(
    () => resolveRole(client, role),
    (resolved) => resolved === expectedId,
    { timeoutMs, intervalMs: 2000 },
  );
}

export const id = "s3";

export async function run(ctx) {
  const { client, log } = ctx;

  const originalId = await resolveRole(client, "temperature");
  assert(originalId, "S3: temperature role did not resolve before rename");
  log(`S3: temperature currently ${originalId}`);

  const hostileId = "sensor.my_renamed_thermometer_xyz";

  log(`S3: renaming ${originalId} -> ${hostileId}`);
  await client.renameEntity(originalId, hostileId);
  const afterRename = await waitForRole(client, "temperature", hostileId);
  assert(
    afterRename.ok,
    `S3: role did not follow rename (still ${afterRename.state}, wanted ${hostileId})`,
  );
  log("S3: role followed the rename");

  log(`S3: renaming back ${hostileId} -> ${originalId}`);
  await client.renameEntity(hostileId, originalId);
  const afterRestore = await waitForRole(client, "temperature", originalId);
  assert(
    afterRestore.ok,
    `S3: role did not follow the rename back (still ${afterRestore.state})`,
  );
  log("S3: role followed the rename back");
}
