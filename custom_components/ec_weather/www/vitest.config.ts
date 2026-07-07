/**
 * Vitest configuration for the ec_weather card tests.
 *
 * The card is a single plain-JS ES module (ec-weather-card.js) — no build
 * step, no TypeScript, no lit. Tests import its exported pure helpers
 * directly and exercise them against jsdom.
 *
 * No coverage thresholds yet: unlike popup-card, most of this file is
 * shadow-DOM render code that the behavioral tests reach only through the
 * extracted pure functions. Thresholds come once the render paths are
 * decomposed enough for the numbers to be meaningful.
 */

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["__tests__/setup.js"],
    include: ["__tests__/**/*.test.js"],
    passWithNoTests: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["ec-weather-card.js"],
      exclude: ["__tests__/**"],
    },
  },
});
