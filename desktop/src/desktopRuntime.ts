import { execFileSync } from "node:child_process";
import type { DesktopChannelSpec } from "./env.js";

const STATUS_COMMAND = "transport-matters";
const STATUS_COMMAND_TIMEOUT_MS = 2_000;
const RECLAIM_COMMAND_TIMEOUT_MS = 12_000;

export type DesktopRuntimeState =
  | "absent"
  | "live"
  | "stale"
  | "unhealthy"
  | "not-serving"
  | "wedged";

export interface DesktopRuntimeStatus {
  channel: string;
  defaultRouteUrl: string | null;
  proxyPort: number | null;
  state: DesktopRuntimeState;
  webPort: number | null;
}

export type DesktopRuntimeStatusCommand = (
  channel: string,
  env: NodeJS.ProcessEnv,
) => string;

export type DesktopRuntimeReclaimCommand = (
  channel: string,
  workspaceDir: string,
  env: NodeJS.ProcessEnv,
) => void;

export type DesktopRuntimeStatusReader = (
  spec: DesktopChannelSpec,
  env: NodeJS.ProcessEnv,
) => DesktopRuntimeStatus | null;

export type DesktopRuntimeReclaimer = (
  spec: DesktopChannelSpec,
  env: NodeJS.ProcessEnv,
  workspaceDir: string,
) => void;

export interface DesktopRuntimeDiscoveryOptions {
  readRuntimeStatus?: DesktopRuntimeStatusReader;
  runtimeStatus?: DesktopRuntimeStatus | null;
}

export function readDesktopRuntimeStatus(
  spec: DesktopChannelSpec,
  env: NodeJS.ProcessEnv = process.env,
  runStatusCommand: DesktopRuntimeStatusCommand = runDesktopRuntimeStatusCommand,
): DesktopRuntimeStatus | null {
  try {
    const status = parseDesktopRuntimeStatus(
      runStatusCommand(spec.id, env),
    );
    return status.channel === spec.id ? status : null;
  } catch {
    return null;
  }
}

export function resolveRuntimeStatus(
  spec: DesktopChannelSpec,
  env: NodeJS.ProcessEnv,
  options: DesktopRuntimeDiscoveryOptions = {},
): DesktopRuntimeStatus | null {
  if (options.runtimeStatus !== undefined) {
    return options.runtimeStatus;
  }
  const readRuntimeStatus =
    options.readRuntimeStatus ?? readDesktopRuntimeStatus;
  return readRuntimeStatus(spec, env);
}

export function liveRuntimePorts(status: DesktopRuntimeStatus | null): {
  proxyPort?: number;
  webPort?: number;
} {
  if (status?.state !== "live") {
    return {};
  }
  return {
    ...(status.proxyPort !== null ? { proxyPort: status.proxyPort } : {}),
    ...(status.webPort !== null ? { webPort: status.webPort } : {}),
  };
}

export function reclaimDesktopRuntime(
  spec: DesktopChannelSpec,
  env: NodeJS.ProcessEnv = process.env,
  workspaceDir = process.cwd(),
  runReclaimCommand: DesktopRuntimeReclaimCommand = runDesktopRuntimeReclaimCommand,
): void {
  runReclaimCommand(spec.id, workspaceDir, env);
}

export function parseDesktopRuntimeStatus(
  raw: string,
): DesktopRuntimeStatus {
  const payload = JSON.parse(raw) as unknown;
  if (!isRecord(payload) || !isRecord(payload.runtime)) {
    throw new Error("Invalid Transport Matters desktop runtime status.");
  }

  const runtime = payload.runtime;
  return {
    channel: requireString(runtime.channel),
    defaultRouteUrl: optionalString(runtime.defaultRouteUrl),
    proxyPort: optionalPort(runtime.proxyPort),
    state: requireState(runtime.state),
    webPort: optionalPort(runtime.webPort),
  };
}

function runDesktopRuntimeStatusCommand(
  channel: string,
  env: NodeJS.ProcessEnv,
): string {
  return execFileSync(
    STATUS_COMMAND,
    ["channel", "status", channel, "--json"],
    {
      encoding: "utf8",
      env,
      stdio: ["ignore", "pipe", "ignore"],
      timeout: STATUS_COMMAND_TIMEOUT_MS,
    },
  );
}

function runDesktopRuntimeReclaimCommand(
  channel: string,
  workspaceDir: string,
  env: NodeJS.ProcessEnv,
): void {
  execFileSync(
    STATUS_COMMAND,
    ["_desktop-reclaim", "--work-dir", workspaceDir, "--channel", channel],
    {
      env,
      stdio: "pipe",
      timeout: RECLAIM_COMMAND_TIMEOUT_MS,
    },
  );
}

function requireState(value: unknown): DesktopRuntimeState {
  if (
    value === "absent" ||
    value === "live" ||
    value === "stale" ||
    value === "unhealthy" ||
    value === "not-serving" ||
    value === "wedged"
  ) {
    return value;
  }
  throw new Error("Invalid Transport Matters desktop runtime state.");
}

function optionalPort(value: unknown): number | null {
  if (value === null) {
    return null;
  }
  if (
    !Number.isInteger(value) ||
    typeof value !== "number" ||
    value < 1 ||
    value > 65_535
  ) {
    throw new Error("Invalid Transport Matters desktop runtime port.");
  }
  return value;
}

function optionalString(value: unknown): string | null {
  if (value === null) {
    return null;
  }
  return requireString(value);
}

function requireString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("Invalid Transport Matters desktop runtime string.");
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
