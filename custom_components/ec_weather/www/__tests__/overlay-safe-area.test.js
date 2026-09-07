/**
 * ECOverlay mobile safe-area insets.
 *
 * HA renders with viewport-fit=cover, so the full-screen overlay content
 * sits underneath the iOS status bar / home indicator unless it pays the
 * inset back itself (see popup-card.js 1.4.1 for the reference fix). The
 * overlay is built as an innerHTML string with an inline <style> block, so
 * there is nothing importable to exercise — this pins the emitted CSS text
 * directly, the same way hourly-strip.test.js pins STRIP_CSS.
 *
 * jsdom cannot evaluate env() or lay anything out, so this only guards that
 * the correct rules are emitted, not that the visual bug is fixed.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

describe("ECOverlay — mobile block pays back the safe-area insets", () => {
  // vitest runs with cwd = www/, next to the card module.
  const source = readFileSync("ec-weather-card.js", "utf8");
  const overlayBlock = source.slice(
    source.indexOf("class ECOverlay"), source.indexOf("class ECWeatherCard"));
  const mobileBlock = overlayBlock.slice(
    overlayBlock.indexOf("@media (max-width: 768px)"));

  it("adds all four safe-area insets on top of the existing 24px padding", () => {
    expect(mobileBlock).toContain("padding-top: calc(24px + env(safe-area-inset-top, 0px));");
    expect(mobileBlock).toContain("padding-bottom: calc(24px + env(safe-area-inset-bottom, 0px));");
    expect(mobileBlock).toContain("padding-left: calc(24px + env(safe-area-inset-left, 0px));");
    expect(mobileBlock).toContain("padding-right: calc(24px + env(safe-area-inset-right, 0px));");
  });

  it("shifts the close button below the status bar inset", () => {
    expect(mobileBlock).toContain(".ec-overlay-close { top: calc(12px + env(safe-area-inset-top, 0px)); }");
  });
});
