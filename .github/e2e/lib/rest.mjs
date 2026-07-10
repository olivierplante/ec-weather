/**
 * REST helpers for HA config entries.
 *
 * Config-entry REMOVAL is not a websocket command in HA — the frontend uses
 * REST: DELETE /api/config/config_entries/entry/{entry_id}. Listing entries is
 * also available over REST (GET /api/config/config_entries/entry), which the
 * idempotent-setup path uses to find an existing entry after an
 * already_configured abort.
 */

const authHeaders = (token) => ({ Authorization: `Bearer ${token}` });

/** All config entries (every domain) as an array of entry objects. */
export async function listConfigEntries(baseUrl, token) {
  const response = await fetch(`${baseUrl}/api/config/config_entries/entry`, {
    headers: authHeaders(token),
  });
  if (!response.ok) {
    throw new Error(`rest: listing config entries failed (HTTP ${response.status})`);
  }
  return response.json();
}

/** Pure: the subset of entries belonging to a domain. */
export function filterEntriesByDomain(entries, domain) {
  return (entries || []).filter((entry) => entry && entry.domain === domain);
}

/**
 * Delete a config entry over REST.
 *
 * @returns true when deleted, false when it was already gone (404) — a retry
 *   re-running a removal must not fail on an entry deleted the first time.
 */
export async function deleteConfigEntry(baseUrl, token, entryId) {
  const response = await fetch(
    `${baseUrl}/api/config/config_entries/entry/${entryId}`,
    { method: "DELETE", headers: authHeaders(token) },
  );
  if (response.status === 404) return false;
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`rest: deleting entry ${entryId} failed (HTTP ${response.status}): ${text}`);
  }
  return true;
}
