/**
 * REST onboarding for a fresh HA instance.
 *
 * Walks HA's onboarding: create the owner user (returns an auth code), exchange
 * it for an access token via the standard authorization_code grant (client_id
 * is the instance base URL, per the auth API), then complete the remaining
 * onboarding steps so the instance is fully set up. Location is set separately
 * over the WebSocket API (config/core/update) once connected — see ws.mjs.
 *
 * Dependency-free (global fetch). Exercised only in CI.
 */

const jsonHeaders = { "Content-Type": "application/json" };

async function postJson(url, body, headers = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { ...jsonHeaders, ...headers },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`onboarding: HTTP ${response.status} from ${url}: ${text}`);
  }
  return text ? JSON.parse(text) : {};
}

/**
 * Onboard a fresh instance and return an access token.
 *
 * @param {string} baseUrl  e.g. http://127.0.0.1:8123
 * @returns {{ accessToken: string, refreshToken: string, clientId: string }}
 */
export async function onboard(
  baseUrl,
  { name = "E2E Owner", username = "e2e", password = "e2e-password", language = "en" } = {},
) {
  const clientId = `${baseUrl}/`;

  // 1. Create the owner user — returns a one-time auth code.
  const { auth_code: authCode } = await postJson(`${baseUrl}/api/onboarding/users`, {
    client_id: clientId,
    name,
    username,
    password,
    language,
  });
  if (!authCode) {
    throw new Error("onboarding: user creation returned no auth_code");
  }

  // 2. Exchange the auth code for tokens (form-encoded, per the auth API).
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code: authCode,
    client_id: clientId,
  });
  const tokenResponse = await fetch(`${baseUrl}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const tokenText = await tokenResponse.text();
  if (!tokenResponse.ok) {
    throw new Error(`onboarding: token exchange failed (${tokenResponse.status}): ${tokenText}`);
  }
  const tokens = JSON.parse(tokenText);

  // 3. Complete the remaining onboarding steps (authenticated). Each is
  //    idempotent-ish: a step already done answers 403, which we tolerate.
  const authHeaders = { Authorization: `Bearer ${tokens.access_token}` };
  await completeStep(`${baseUrl}/api/onboarding/core_config`, {}, authHeaders);
  await completeStep(`${baseUrl}/api/onboarding/analytics`, {}, authHeaders);
  await completeStep(
    `${baseUrl}/api/onboarding/integration`,
    { client_id: clientId, redirect_uri: clientId },
    authHeaders,
  );

  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    clientId,
  };
}

/** POST an onboarding step, tolerating a 403 (step already completed). */
async function completeStep(url, body, headers) {
  const response = await fetch(url, {
    method: "POST",
    headers: { ...jsonHeaders, ...headers },
    body: JSON.stringify(body),
  });
  if (response.ok || response.status === 403) return;
  const text = await response.text();
  throw new Error(`onboarding: step ${url} failed (${response.status}): ${text}`);
}
