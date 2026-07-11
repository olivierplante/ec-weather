/**
 * Unit tests for the pure parts of the docker helper. Runs without docker.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildConfigurationYaml, imageRef } from "../lib/docker.mjs";

test("buildConfigurationYaml keeps default_config (standard HA integrations)", () => {
  const yaml = buildConfigurationYaml();
  assert.match(yaml, /^default_config:$/m);
});

test("buildConfigurationYaml keeps the global log level at warning", () => {
  const yaml = buildConfigurationYaml();
  assert.match(yaml, /^logger:$/m);
  assert.match(yaml, /^ {2}default: warning$/m);
});

test("buildConfigurationYaml raises only the component logger to info", () => {
  const yaml = buildConfigurationYaml();
  // The S4-asserted "restored forecast cache" line is INFO from
  // custom_components.ec_weather.* — invisible at the container's
  // warning-and-above default without this override.
  assert.match(yaml, /^ {4}custom_components\.ec_weather: info$/m);
  // No other logger is raised.
  const infoLines = yaml.split("\n").filter((line) => line.endsWith(": info"));
  assert.equal(infoLines.length, 1);
});

test("buildConfigurationYaml ends with a newline and uses spaces only", () => {
  const yaml = buildConfigurationYaml();
  assert.ok(yaml.endsWith("\n"));
  assert.ok(!yaml.includes("\t"), "YAML must not contain tabs");
});

test("imageRef resolves stable — the only supported target (no pinning)", () => {
  assert.equal(imageRef("stable"), "ghcr.io/home-assistant/home-assistant:stable");
});

test("imageRef still accepts an arbitrary tag (local --ha-version override)", () => {
  assert.equal(imageRef("2026.7.1"), "ghcr.io/home-assistant/home-assistant:2026.7.1");
});
