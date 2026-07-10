/**
 * Card entity discovery (Phase 2): the async role resolver that replaces the
 * hardcoded entity_ids.
 *
 * The card reads its entities by a stable machine-readable ROLE, resolved at
 * runtime from the ec_weather/entities websocket command. These tests cover the
 * shared module-level resolver (one command call for all card instances), the
 * legacy fallback, per-card device selection, re-resolution on registry events,
 * availability gating on resolved ids, and the issue #12 rename scenario. A
 * source-text enforcement test bans hardcoded ids outside the fallback map.
 */

import { readFileSync } from "node:fs";

import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  ECWeatherCard,
  LEGACY_ENTITY_IDS,
  getResolverState,
  resetResolver,
  resolveEntities,
  selectEntry,
} from "../ec-weather-card.js";

beforeAll(() => {
  if (!customElements.get("ec-weather-card")) {
    customElements.define("ec-weather-card", ECWeatherCard);
  }
});

beforeEach(() => {
  resetResolver();
});

// ── Stubs ────────────────────────────────────────────────────────────────────

const state = (value, attributes = {}) => ({
  state: String(value),
  attributes,
  last_updated: new Date().toISOString(),
});

// A minimal states map that lets the current section render end-to-end. The
// temperature entity_id is parameterized so the rename scenario can move it.
const buildStates = (tempId = "sensor.ec_temperature") => ({
  [tempId]: state("25.8", { fetched_at: new Date().toISOString() }),
  "sensor.ec_feels_like": state("27.0"),
  "sensor.ec_wind_speed": state("13"),
  "sensor.ec_wind_direction": state("NW"),
  "sensor.ec_condition": state("Mainly sunny"),
  "sensor.ec_icon_code": state("1"),
  "sensor.ec_daily_forecast": state("ok", { forecast: [] }),
  "sun.sun": state("above_horizon"),
});

// Command-mode roles: same short ids as today, temperature parameterized.
const buildRoles = (tempId = "sensor.ec_temperature") => ({
  ...LEGACY_ENTITY_IDS,
  temperature: tempId,
});

const buildEntry = (overrides = {}) => ({
  entry_id: "entry_a",
  device_id: "device_a",
  city_name: "TestCity",
  roles: buildRoles(),
  ...overrides,
});

function makeConnection(initialEntries, { fail = false } = {}) {
  const connection = {
    _entries: initialEntries,
    _handlers: {},
    setEntries(next) {
      this._entries = next;
    },
    fire(eventType) {
      const handler = this._handlers[eventType];
      if (handler) handler({});
    },
    sendMessagePromise: vi.fn(function sendMessagePromise() {
      if (fail) return Promise.reject(new Error("unknown_command"));
      return Promise.resolve({ entries: connection._entries });
    }),
    subscribeEvents: vi.fn((handler, eventType) => {
      connection._handlers[eventType] = handler;
      return Promise.resolve(() => {});
    }),
    addEventListener: vi.fn((eventType, handler) => {
      connection._handlers[eventType] = handler;
    }),
  };
  return connection;
}

const makeHass = (states, connection) => ({
  language: "en",
  themes: { darkMode: true },
  locale: { time_format: "24" },
  config: { latitude: 45.5 },
  callService: vi.fn(),
  connection,
  states,
});

// Awaits the shared resolution promise plus one microtask so the .then that
// updates state and notifies listeners has run.
const settle = async () => {
  await getResolverState().promise;
  await Promise.resolve();
};

const mountCard = (section, hass) => {
  const card = document.createElement("ec-weather-card");
  card.setConfig({ section });
  document.body.appendChild(card); // fires connectedCallback → registers listener
  card.hass = hass;
  return card;
};

// ── Resolver: shared command call, success, fallback ─────────────────────────

describe("resolveEntities — shared resolution", () => {
  it("issues a single command call shared by all callers", async () => {
    const connection = makeConnection([buildEntry()]);
    const hass = makeHass(buildStates(), connection);
    const first = resolveEntities(hass);
    const second = resolveEntities(hass);
    expect(first).toBe(second);
    await first;
    expect(connection.sendMessagePromise).toHaveBeenCalledTimes(1);
  });

  it("populates command roles on success", async () => {
    const connection = makeConnection([buildEntry()]);
    await resolveEntities(makeHass(buildStates(), connection));
    const resolver = getResolverState();
    expect(resolver.source).toBe("command");
    expect(resolver.entries[0].roles.temperature).toBe("sensor.ec_temperature");
  });

  it("falls back to LEGACY_ENTITY_IDS when the command errors", async () => {
    const connection = makeConnection(null, { fail: true });
    await resolveEntities(makeHass(buildStates(), connection));
    expect(getResolverState().source).toBe("fallback");
  });

  it("falls back when the command returns zero entries", async () => {
    const connection = makeConnection([]);
    await resolveEntities(makeHass(buildStates(), connection));
    expect(getResolverState().source).toBe("fallback");
  });

  it("falls back synchronously when there is no websocket connection", () => {
    resolveEntities(makeHass(buildStates(), undefined));
    expect(getResolverState().source).toBe("fallback");
  });

  it("legacy map covers every role and holds only literal entity ids", () => {
    for (const value of Object.values(LEGACY_ENTITY_IDS)) {
      expect(value).toMatch(/^(sensor|binary_sensor)\.ec_/);
    }
  });
});

// ── Entry selection ──────────────────────────────────────────────────────────

describe("selectEntry — per-card device selection", () => {
  const alpha = { entry_id: "e_alpha", device_id: "d_alpha", city_name: "Alphaville", roles: {} };
  const beta = { entry_id: "e_beta", device_id: "d_beta", city_name: "Betatown", roles: {} };

  it("auto-selects the only entry", () => {
    expect(selectEntry([alpha], {})).toBe(alpha);
  });

  it("matches the device option against city_name, case-insensitive", () => {
    expect(selectEntry([alpha, beta], { device: "betatown" })).toBe(beta);
  });

  it("matches the device option against device_id", () => {
    expect(selectEntry([alpha, beta], { device: "d_alpha" })).toBe(alpha);
  });

  it("matches the device option against entry_id", () => {
    expect(selectEntry([alpha, beta], { device: "e_beta" })).toBe(beta);
  });

  it("picks alphabetically by city_name when multiple and no device", () => {
    expect(selectEntry([beta, alpha], {})).toBe(alpha);
  });
});

describe("multi-device hint", () => {
  it("logs a one-line hint once when multiple entries and no device config", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const entries = [
      buildEntry({ entry_id: "e_a", city_name: "Alphaville", roles: buildRoles() }),
      buildEntry({ entry_id: "e_b", city_name: "Betatown", roles: buildRoles() }),
    ];
    const connection = makeConnection(entries);
    const card = mountCard("current", makeHass(buildStates(), connection));
    await settle();
    expect(info).toHaveBeenCalledTimes(1);
    expect(String(info.mock.calls[0][0])).toContain("device");
    document.body.removeChild(card);
    info.mockRestore();
  });
});

// ── Re-resolution on registry events ─────────────────────────────────────────

describe("re-resolution", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-issues the command (debounced) on a registry update and notifies on change", async () => {
    const connection = makeConnection([buildEntry({ roles: buildRoles() })]);
    const card = mountCard("current", makeHass(buildStates(), connection));
    await vi.runAllTimersAsync(); // initial resolution settles
    expect(connection.sendMessagePromise).toHaveBeenCalledTimes(1);

    const listener = vi.fn();
    getResolverState().listeners.add(listener);

    // Registry update with a CHANGED payload (temperature moved).
    connection.setEntries([buildEntry({ roles: buildRoles("sensor.ec_temperature_renamed") })]);
    connection.fire("entity_registry_updated");
    await vi.advanceTimersByTimeAsync(600);

    expect(connection.sendMessagePromise).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenCalled();
    expect(getResolverState().entries[0].roles.temperature).toBe("sensor.ec_temperature_renamed");
    document.body.removeChild(card);
  });

  it("does not notify when the re-resolved payload is unchanged", async () => {
    const connection = makeConnection([buildEntry({ roles: buildRoles() })]);
    const card = mountCard("current", makeHass(buildStates(), connection));
    await vi.runAllTimersAsync();

    const listener = vi.fn();
    getResolverState().listeners.add(listener);

    connection.fire("entity_registry_updated"); // same entries
    await vi.advanceTimersByTimeAsync(600);

    expect(connection.sendMessagePromise).toHaveBeenCalledTimes(2);
    expect(listener).not.toHaveBeenCalled();
    document.body.removeChild(card);
  });
});

// ── Gating on resolved ids ───────────────────────────────────────────────────

describe("availability gating on resolved ids", () => {
  it("renders the section when required roles resolve to available states", async () => {
    const connection = makeConnection([buildEntry()]);
    const card = mountCard("current", makeHass(buildStates(), connection));
    await settle();
    expect(card.shadowRoot.innerHTML).toContain("26°");
    document.body.removeChild(card);
  });

  it("renders the unavailable state when a required entity is unavailable", async () => {
    const connection = makeConnection([buildEntry()]);
    const states = buildStates();
    states["sensor.ec_temperature"] = state("unavailable");
    const card = mountCard("current", makeHass(states, connection));
    await settle();
    expect(card.shadowRoot.innerHTML).toContain("Weather data unavailable");
    document.body.removeChild(card);
  });

  it("shows loading, not the unavailable state, while resolution is pending", () => {
    const connection = {
      sendMessagePromise: () => new Promise(() => {}), // never resolves
      subscribeEvents: () => Promise.resolve(() => {}),
      addEventListener: () => {},
    };
    const card = mountCard("current", makeHass(buildStates(), connection));
    const html = card.shadowRoot.innerHTML;
    expect(html).toContain("mdi:loading");
    expect(html).not.toContain("Weather data unavailable");
    document.body.removeChild(card);
  });
});

// ── Issue #12: a registry rename keeps the card working ──────────────────────

describe("registry rename scenario (issue #12)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reads the new entity_id after a rename and keeps rendering", async () => {
    const connection = makeConnection([buildEntry({ roles: buildRoles() })]);
    const card = mountCard("current", makeHass(buildStates(), connection));
    await vi.runAllTimersAsync();
    expect(card.shadowRoot.innerHTML).toContain("26°");

    // Rename: the temperature entity moves to a new id.
    const renamedId = "sensor.ec_temperature_renamed";
    connection.setEntries([buildEntry({ roles: buildRoles(renamedId) })]);
    connection.fire("entity_registry_updated");
    await vi.advanceTimersByTimeAsync(600);

    // A fresh hass carrying the renamed entity arrives.
    card.hass = makeHass(buildStates(renamedId), connection);
    await vi.runAllTimersAsync();

    expect(card.entityIdFor("temperature")).toBe(renamedId);
    expect(card.shadowRoot.innerHTML).toContain("26°");
    document.body.removeChild(card);
  });
});

// ── Enforcement: no hardcoded ids outside the fallback map ────────────────────

describe("no hardcoded entity ids outside the legacy fallback map", () => {
  it("has literal ec_ entity ids only inside LEGACY_ENTITY_IDS", () => {
    const source = readFileSync("ec-weather-card.js", "utf8");
    const startMarker = "// ── LEGACY_ENTITY_IDS:START";
    const endMarker = "// ── LEGACY_ENTITY_IDS:END";
    const startIdx = source.indexOf(startMarker);
    const endIdx = source.indexOf(endMarker);
    expect(startIdx).toBeGreaterThan(-1);
    expect(endIdx).toBeGreaterThan(startIdx);
    const outside = source.slice(0, startIdx) + source.slice(endIdx);
    expect(outside).not.toMatch(/sensor\.ec_/);
    expect(outside).not.toMatch(/binary_sensor\.ec_/);
  });
});
