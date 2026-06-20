/**
 * Canonical `TRANSPORT_MATTERS_*` env keys shared between the writer
 * (`backendProcess`) and the readers (`main`). Deriving each key from the prefix
 * keeps the writer and readers on one symbol and makes the littleorgans monorepo
 * rename a one-line change. Mirrors `api/src/transport_matters/env_keys.py`;
 * rename both together. See `NOTES/env-vars-transport-prefix.md`.
 */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ENV_PREFIX = "TRANSPORT_MATTERS_";
const DEFAULT_CHANNEL_ID = "stable";
const CHANNEL_SPECS_URL = new URL("./channel-specs.json", import.meta.url);
const SOURCE_CHANNEL_SPECS_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../api/src/transport_matters/channel-specs.json",
);

export const ENV = {
  CHANNEL: `${ENV_PREFIX}CHANNEL`,
  CWD: `${ENV_PREFIX}CWD`,
  PROXY_PORT: `${ENV_PREFIX}PROXY_PORT`,
  WEB_PORT: `${ENV_PREFIX}WEB_PORT`,
  DESKTOP_CLIENT: `${ENV_PREFIX}DESKTOP_CLIENT`,
  DESKTOP_ROUTE_URL: `${ENV_PREFIX}DESKTOP_ROUTE_URL`,
  DESKTOP_SMOKE_FILE: `${ENV_PREFIX}DESKTOP_SMOKE_FILE`,
  DESKTOP_PACKAGE_SMOKE: `${ENV_PREFIX}DESKTOP_PACKAGE_SMOKE`,
} as const;

export interface DesktopChannelBadge {
  text: string;
  color: "amber";
  hex: string;
}

export interface DesktopChannelSpec {
  id: string;
  label: string;
  home: string;
  databaseName: string;
  proxyPort: number;
  webPort: number;
  electron: {
    appName: string;
    appId: string;
    userDataDir: string | null;
    dockIcon: "default" | "preview-amber";
  };
  badge: DesktopChannelBadge | null;
}

export function resolveDesktopChannelSpec(
  env: NodeJS.ProcessEnv = process.env,
): DesktopChannelSpec {
  const channelId = env[ENV.CHANNEL] ?? DEFAULT_CHANNEL_ID;
  const spec = readDesktopChannelSpecs().find((candidate) => candidate.id === channelId);
  if (spec === undefined) {
    throw new Error(`Unknown Transport Matters channel: ${channelId}`);
  }
  return spec;
}

function readDesktopChannelSpecs(): DesktopChannelSpec[] {
  const raw = JSON.parse(
    readFileSync(resolveChannelSpecsPath(), "utf8"),
  ) as unknown;
  return parseDesktopChannelSpecs(raw);
}

function resolveChannelSpecsPath(): string {
  const distPath = fileURLToPath(CHANNEL_SPECS_URL);
  if (existsSync(distPath)) {
    return distPath;
  }
  return SOURCE_CHANNEL_SPECS_PATH;
}

function parseDesktopChannelSpecs(raw: unknown): DesktopChannelSpec[] {
  if (!isRecord(raw) || raw.schema !== 1 || !Array.isArray(raw.channels)) {
    throw new Error("Invalid Transport Matters channel specs.");
  }
  return raw.channels.map(normalizeChannelSpec);
}

function normalizeChannelSpec(raw: unknown): DesktopChannelSpec {
  if (!isRecord(raw) || !isRecord(raw.electron)) {
    throw new Error("Invalid Transport Matters channel entry.");
  }
  const electron = raw.electron;
  const home = join(homedir(), requireString(raw, "homeDir"));
  const dockIcon = requireString(electron, "dockIcon");
  if (dockIcon !== "default" && dockIcon !== "preview-amber") {
    throw new Error(`Unsupported Transport Matters dock icon: ${String(dockIcon)}`);
  }
  return {
    id: requireString(raw, "id"),
    label: requireString(raw, "label"),
    home,
    databaseName: requireString(raw, "databaseName"),
    proxyPort: requirePort(raw, "proxyPort"),
    webPort: requirePort(raw, "webPort"),
    electron: {
      appName: requireString(electron, "appName"),
      appId: requireString(electron, "appId"),
      userDataDir: optionalString(electron, "userDataDir"),
      dockIcon,
    },
    badge: normalizeBadge(raw.badge),
  };
}

function normalizeBadge(raw: unknown): DesktopChannelBadge | null {
  if (raw === null) {
    return null;
  }
  if (!isRecord(raw) || raw.color !== "amber") {
    throw new Error("Invalid Transport Matters channel badge.");
  }
  return {
    text: requireString(raw, "text"),
    color: "amber",
    hex: requireString(raw, "hex"),
  };
}

function requireString(data: Record<string, unknown>, key: string): string {
  const value = data[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Invalid Transport Matters channel string: ${key}`);
  }
  return value;
}

function optionalString(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Invalid Transport Matters channel optional string: ${key}`);
  }
  return value;
}

function requirePort(data: Record<string, unknown>, key: string): number {
  const value = data[key];
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > 65535
  ) {
    throw new Error(`Invalid Transport Matters channel port: ${key}`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
