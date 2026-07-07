// Mark the environment as a test run BEFORE ec-weather-card.js is imported,
// so its registration block (customElements.define + window.customCards push
// + console banner) is skipped. Tests import the exported pure helpers.
globalThis.window = globalThis.window || globalThis;
window.__EC_WEATHER_CARD_TEST__ = true;
