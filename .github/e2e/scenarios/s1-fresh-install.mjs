/**
 * S1 — Fresh install (Newmarket), mirrors issue #12.
 *
 * On a virgin registry: complete the config flow, confirm the role resolver
 * returns every required role, the gating entities got their pinned SHORT ids
 * (the issue-#12 regression was device-prefixed/absent ids on fresh installs),
 * temperature leaves "unknown" within 90s, the forecast attributes populate
 * within 120s, and the card JS URL serves a defined custom element.
 *
 * EC-network-backed data is asserted leniently (existence / leaves-unknown);
 * registry/id behaviour is asserted strictly.
 */

import { assert, pollUntil, rolesCoverRequired, isKnownState, retryOnce } from "../lib/asserts.mjs";
import { ensureConfigEntry } from "../lib/flow-walker.mjs";

// Precip / yesterday roles only exist when a nearby climate station is
// configured, so they are allowed to be absent on a lenient fresh install.
export const OPTIONAL_ROLES = [
  "precip_probability_today",
  "yesterday_rain",
  "yesterday_snow",
  "yesterday_precipitation",
];

// A strict subset that MUST resolve to short ec_* ids on a fresh install.
const GATING_ROLES = [
  "temperature",
  "condition",
  "hourly_forecast",
  "daily_forecast",
  "alerts",
  "alert_active",
];

/** Poll ec_weather/entities until a loaded entry exposes resolved roles. */
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

export const id = "s1";

export async function run(ctx) {
  const { client, baseUrl, token, requiredRoles, log } = ctx;

  log("S1: walking the config flow (Newmarket)");
  // Idempotent: a retry re-running S1 on the same container hits the
  // single-instance already_configured abort and continues with the entry.
  const created = await ensureConfigEntry(baseUrl, token, {
    handler: "ec_weather",
    known: { city_query: "Newmarket", language: "en" },
    preferOptionLabel: { city_id: "Newmarket", city_query: "Newmarket" },
  });
  ctx.entryId = created.entryId;
  log(
    created.created
      ? `S1: config flow created entry ${ctx.entryId}`
      : `S1: entry ${ctx.entryId} already present (retry)`,
  );

  const entry = await waitForLoadedEntry(client);
  const roles = entry.roles;

  const coverage = rolesCoverRequired(roles, requiredRoles, OPTIONAL_ROLES);
  assert(coverage.ok, `missing required roles: ${coverage.missing.join(", ")}`);
  log(`S1: ${Object.keys(roles).length} roles resolved`);

  for (const role of GATING_ROLES) {
    const entityId = roles[role];
    assert(entityId, `gating role ${role} did not resolve`);
    const [domain, objectId] = entityId.split(".");
    const expectedDomain = requiredRoles[role].domain;
    assert(
      domain === expectedDomain,
      `role ${role}: domain ${domain} != expected ${expectedDomain}`,
    );
    // Pinned short id: object_id begins with "ec_" (issue #12 — no device
    // prefix, no city-code suffix leaking into the id).
    assert(
      /^ec_[a-z_]+$/.test(objectId),
      `role ${role}: entity_id ${entityId} is not a pinned short ec_* id`,
    );
  }
  log("S1: gating entities carry pinned short ids");

  const temperatureId = roles.temperature;
  const tempResult = await pollUntil(
    () => client.getState(temperatureId),
    (state) => isKnownState(state),
    { timeoutMs: 90000, intervalMs: 3000 },
  );
  assert(tempResult.ok, `temperature stayed unknown for 90s (last: ${tempResult.state})`);
  log(`S1: temperature settled to ${tempResult.state} after ${tempResult.waitedMs}ms`);

  for (const role of ["hourly_forecast", "daily_forecast"]) {
    const forecastId = roles[role];
    const forecastResult = await pollUntil(
      async () => {
        const stateObject = await client.getStateObject(forecastId);
        const forecast = stateObject && stateObject.attributes && stateObject.attributes.forecast;
        return Array.isArray(forecast) && forecast.length ? "populated" : null;
      },
      (value) => value === "populated",
      { timeoutMs: 120000, intervalMs: 4000 },
    );
    assert(forecastResult.ok, `${role} forecast attribute stayed empty for 120s`);
    log(`S1: ${role} populated after ${forecastResult.waitedMs}ms`);
  }

  await retryOnce(async () => {
    const response = await fetch(`${baseUrl}/ec_weather/ec-weather-card.js`);
    assert(response.status === 200, `card JS returned HTTP ${response.status}`);
    const body = await response.text();
    assert(
      body.includes("customElements.define"),
      "card JS body has no customElements.define",
    );
  });
  log("S1: card JS serves 200 with a defined custom element");
}
