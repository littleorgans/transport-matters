import { spawn as spawnChildProcess } from "node:child_process";
import type { SpawnOptions } from "node:child_process";
import type { EventEmitter } from "node:events";

export const SUPPORTED_BACKEND_CLIENTS = ["claude", "codex"] as const;
export type BackendClient = (typeof SUPPORTED_BACKEND_CLIENTS)[number];

export function isBackendClient(value: string): value is BackendClient {
  return SUPPORTED_BACKEND_CLIENTS.some((client) => client === value);
}

export interface BackendLaunchOptions {
  client: BackendClient;
  env?: NodeJS.ProcessEnv;
  proxyPort: number;
  webPort: number;
  workspaceDir: string;
}

export interface BackendLaunch {
  args: string[];
  command: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
}

export type BackendChildProcess = Pick<EventEmitter, "off" | "once"> & {
  kill(signal?: NodeJS.Signals): boolean;
  killed?: boolean;
};

export interface LaunchedBackendProcess {
  child: BackendChildProcess;
  launch: BackendLaunch;
}

export interface BackendExitWatcher {
  dispose(): void;
  promise: Promise<never>;
}

export type SpawnBackendProcess = (
  command: string,
  args: string[],
  options: SpawnOptions,
) => BackendChildProcess;

export class BackendProcessExitError extends Error {
  constructor(code: number | null, signal: NodeJS.Signals | null) {
    const detail =
      code === null ? `signal ${signal ?? "unknown"}` : `code ${code}`;
    super(`Transport Matters backend exited before readiness with ${detail}.`);
    this.name = "BackendProcessExitError";
  }
}

export class BackendProcessSpawnError extends Error {
  constructor(cause: Error) {
    super(`Transport Matters backend failed before readiness: ${cause.message}`);
    this.name = "BackendProcessSpawnError";
    this.cause = cause;
  }
}

export function buildBackendLaunch(
  options: BackendLaunchOptions,
): BackendLaunch {
  const proxyPort = String(options.proxyPort);
  const webPort = String(options.webPort);

  return {
    args: [
      options.client,
      options.workspaceDir,
      "--web-port",
      webPort,
      "--proxy-port",
      proxyPort,
    ],
    command: "transport-matters",
    cwd: options.workspaceDir,
    env: {
      ...options.env,
      TRANSPORT_MATTERS_PROXY_PORT: proxyPort,
      TRANSPORT_MATTERS_WEB_PORT: webPort,
    },
  };
}

export function launchBackendProcess(
  options: BackendLaunchOptions,
  spawnBackend: SpawnBackendProcess = spawnChildProcess,
): LaunchedBackendProcess {
  const launch = buildBackendLaunch(options);
  const child = spawnBackend(launch.command, launch.args, {
    cwd: launch.cwd,
    env: launch.env,
    stdio: "pipe",
  });

  return { child, launch };
}

export function stopBackendProcess(backend: LaunchedBackendProcess): void {
  if (backend.child.killed) {
    return;
  }
  backend.child.kill("SIGTERM");
}

export function watchBackendExitBeforeReady(
  child: BackendChildProcess,
): BackendExitWatcher {
  const onExit = (code: number | null, signal: NodeJS.Signals | null): void => {
    rejectOnce(new BackendProcessExitError(code, signal));
  };
  const onError = (error: Error): void => {
    rejectOnce(new BackendProcessSpawnError(error));
  };
  let rejectOnce: (error: Error) => void = () => undefined;
  const promise = new Promise<never>((_resolve, reject) => {
    rejectOnce = reject;
    child.once("exit", onExit);
    child.once("error", onError);
  });

  return {
    dispose: () => {
      child.off("exit", onExit);
      child.off("error", onError);
    },
    promise,
  };
}
