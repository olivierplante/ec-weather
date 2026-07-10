/**
 * Minimal Home Assistant WebSocket client (dependency-free).
 *
 * Uses Node's global WebSocket (>= 21). Performs the auth handshake, then
 * offers a promise-based `call` plus the handful of commands the scenarios
 * need: state reads, entity-registry list/update, core-config update, and the
 * integration's own ec_weather/entities role resolver. Exercised only in CI.
 */

/**
 * Connect and authenticate. Resolves to a client object.
 *
 * @param {string} baseUrl  http(s) base, e.g. http://127.0.0.1:8123
 * @param {string} token    access token
 */
export async function connect(baseUrl, token, { timeoutMs = 30000 } = {}) {
  const wsUrl = `${baseUrl.replace(/^http/, "ws")}/api/websocket`;
  const socket = new WebSocket(wsUrl);

  const pending = new Map();
  let nextId = 1;
  let authResolve;
  let authReject;
  const authed = new Promise((resolve, reject) => {
    authResolve = resolve;
    authReject = reject;
  });
  const authTimer = setTimeout(
    () => authReject(new Error("ws: auth handshake timed out")),
    timeoutMs,
  );

  socket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.type === "auth_required") {
      socket.send(JSON.stringify({ type: "auth", access_token: token }));
      return;
    }
    if (message.type === "auth_ok") {
      clearTimeout(authTimer);
      authResolve();
      return;
    }
    if (message.type === "auth_invalid") {
      clearTimeout(authTimer);
      authReject(new Error(`ws: auth invalid (${message.message || "no reason"})`));
      return;
    }
    if (message.type === "result" && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.success) resolve(message.result);
      else reject(new Error(`ws: command failed: ${JSON.stringify(message.error)}`));
    }
  });

  socket.addEventListener("error", (event) => {
    authReject(new Error(`ws: socket error: ${event.message || event.type}`));
  });
  socket.addEventListener("close", () => {
    for (const { reject } of pending.values()) {
      reject(new Error("ws: socket closed before response"));
    }
    pending.clear();
  });

  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  await authed;

  const call = (payload) =>
    new Promise((resolve, reject) => {
      const id = nextId;
      nextId += 1;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ ...payload, id }));
    });

  return {
    call,
    close: () => socket.close(),

    /** All entity states (array of {entity_id, state, attributes}). */
    getStates: () => call({ type: "get_states" }),

    /** The state string of one entity, or null when absent. */
    async getState(entityId) {
      const states = await call({ type: "get_states" });
      const found = states.find((state) => state.entity_id === entityId);
      return found ? found.state : null;
    },

    /** The full state object of one entity, or null when absent. */
    async getStateObject(entityId) {
      const states = await call({ type: "get_states" });
      return states.find((state) => state.entity_id === entityId) || null;
    },

    /** Entity registry entries. */
    listRegistryEntities: () => call({ type: "config/entity_registry/list" }),

    /** Rename an entity via the registry (issue #12 hostility test). */
    renameEntity: (entityId, newEntityId) =>
      call({ type: "config/entity_registry/update", entity_id: entityId, new_entity_id: newEntityId }),

    /** Set the instance's location and units (Newmarket in S1). */
    updateCoreConfig: (config) => call({ type: "config/core/update", ...config }),

    /** Loaded config entries for a domain. */
    listConfigEntries: (domain) => call({ type: "config_entries/get", domain }),

    /** Remove a config entry (S2 delete-and-re-add). */
    removeConfigEntry: (entryId) =>
      call({ type: "config_entries/remove", entry_id: entryId }),

    /** The integration's role resolver — the card's contract. */
    getEcEntities: () => call({ type: "ec_weather/entities" }),
  };
}
