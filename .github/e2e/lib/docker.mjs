/**
 * Docker lifecycle for the official Home Assistant image.
 *
 * Dependency-free: shells out to the `docker` CLI (present on GitHub runners)
 * and uses global fetch to poll for readiness. NOT runnable on this dev machine
 * (no docker) — exercised only in CI.
 */

import { execFile } from "node:child_process";
import { cp, mkdtemp, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const IMAGE_REPO = "ghcr.io/home-assistant/home-assistant";

/** Run a docker subcommand, returning { stdout, stderr }. */
export async function docker(args, { timeoutMs = 120000 } = {}) {
  return execFileAsync("docker", args, { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 });
}

/** Resolve the image reference for a version tag ("2026.7.1" or "stable"). */
export function imageRef(haVersion) {
  return `${IMAGE_REPO}:${haVersion}`;
}

/** Create a fresh temp config directory with an empty custom_components dir. */
export async function makeConfigDir() {
  const dir = await mkdtemp(join(tmpdir(), "ec-e2e-config-"));
  await mkdir(join(dir, "custom_components"), { recursive: true });
  return dir;
}

/**
 * Install (or replace) the ec_weather component into a config dir from a source
 * custom_components/ec_weather tree (the PR checkout or a downloaded release).
 */
export async function installComponent(configDir, sourceComponentDir) {
  const target = join(configDir, "custom_components", "ec_weather");
  await rm(target, { recursive: true, force: true });
  await cp(sourceComponentDir, target, { recursive: true });
}

/**
 * Start a detached HA container.
 *
 * @returns {{ name: string, port: number, configDir: string, baseUrl: string }}
 */
export async function startContainer({ haVersion, port = 8123, configDir, name }) {
  const containerName = name || `ec-e2e-${Date.now()}`;
  await docker([
    "run", "-d",
    "--name", containerName,
    "-p", `${port}:8123`,
    "-v", `${configDir}:/config`,
    "-e", "TZ=America/Toronto",
    imageRef(haVersion),
  ]);
  return { name: containerName, port, configDir, baseUrl: `http://127.0.0.1:${port}` };
}

/** Restart a running container (used by S4 to test cache persistence). */
export async function restartContainer(name) {
  await docker(["restart", name]);
}

/** Return the container's stdout/stderr logs as a single string. */
export async function containerLogs(name) {
  const { stdout, stderr } = await docker(["logs", name]);
  return `${stdout}\n${stderr}`;
}

/** Force-remove a container, ignoring "no such container" errors. */
export async function removeContainer(name) {
  try {
    await docker(["rm", "-f", name]);
  } catch (error) {
    if (!/no such container/i.test(String(error.stderr || error.message))) throw error;
  }
}

/**
 * Poll an HTTP endpoint until it answers (any status) or the timeout elapses.
 * HA serves the frontend on `/` once core has started.
 */
export async function waitForHttp(baseUrl, { timeoutMs = 180000, intervalMs = 3000 } = {}) {
  const started = Date.now();
  let lastError = null;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(`${baseUrl}/`, { redirect: "manual" });
      // Any HTTP answer (200, 302 to onboarding, 401) means core is up.
      if (response.status > 0) return true;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(
    `waitForHttp: ${baseUrl} did not answer within ${timeoutMs}ms (last: ${lastError})`,
  );
}
