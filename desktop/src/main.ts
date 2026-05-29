import { app, BrowserWindow, dialog } from "electron";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  SUPPORTED_BACKEND_CLIENTS,
  isBackendClient,
  launchBackendProcess,
  stopBackendProcess,
  watchBackendExitBeforeReady,
  type BackendClient,
  type BackendLaunchOptions,
  type LaunchedBackendProcess,
} from "./backendProcess.js";
import { waitForBackendHealth } from "./backendHealth.js";
import {
  DEFAULT_WEB_PORT,
  createHostedWindow,
  rendererUrlForPort,
} from "./window.js";

const moduleDir = dirname(fileURLToPath(import.meta.url));

const DEFAULT_PROXY_PORT = 8787;

export interface MainWindowOptions {
  preloadPath?: string;
  rendererUrl?: string;
}

export interface BackendStartupOptions extends BackendLaunchOptions {
  preloadPath?: string;
}

export interface BackendStartupDependencies {
  createWindow?: (options: MainWindowOptions) => BrowserWindow;
  launchBackend?: (
    options: BackendLaunchOptions,
  ) => LaunchedBackendProcess;
  stopBackend?: (backend: LaunchedBackendProcess) => void;
  waitForHealth?: (
    backend: LaunchedBackendProcess,
    webPort: number,
  ) => Promise<void>;
}

export interface AppQuitSource {
  on(event: "before-quit", listener: () => void): void;
}

export interface AppReadySource {
  quit(): void;
  whenReady(): Promise<void>;
}

export interface DesktopPackageSmokeOptions {
  appSource?: AppReadySource;
  createWindow?: (options: MainWindowOptions) => BrowserWindow;
  env?: NodeJS.ProcessEnv;
  writeFile?: (path: string, data: string) => void;
}

export function resolvePreloadPath(): string {
  return join(moduleDir, "preload.js");
}

export function createMainWindow(
  options: MainWindowOptions = {},
): BrowserWindow {
  return createHostedWindow({
    preloadPath: options.preloadPath ?? resolvePreloadPath(),
    rendererUrl: options.rendererUrl,
  });
}

export function resolveBackendStartupOptions(
  env: NodeJS.ProcessEnv = process.env,
  cwd = process.cwd(),
): BackendStartupOptions {
  return {
    client: resolveBackendClient(env.TRANSPORT_MATTERS_DESKTOP_CLIENT),
    env: { ...env },
    proxyPort: resolvePort(env.TRANSPORT_MATTERS_PROXY_PORT, DEFAULT_PROXY_PORT),
    webPort: resolvePort(env.TRANSPORT_MATTERS_WEB_PORT, DEFAULT_WEB_PORT),
    workspaceDir: cwd,
  };
}

export async function waitForLaunchedBackend(
  backend: LaunchedBackendProcess,
  webPort: number,
): Promise<void> {
  const exitWatcher = watchBackendExitBeforeReady(backend.child);
  try {
    await Promise.race([
      waitForBackendHealth({ webPort }),
      exitWatcher.promise,
    ]);
  } finally {
    exitWatcher.dispose();
  }
}

export async function startBackendAndCreateWindow(
  options: BackendStartupOptions,
  dependencies: BackendStartupDependencies = {},
): Promise<BrowserWindow> {
  const launchBackend = dependencies.launchBackend ?? launchBackendProcess;
  const stopBackend = dependencies.stopBackend ?? stopBackendProcess;
  const waitForHealth = dependencies.waitForHealth ?? waitForLaunchedBackend;
  const createWindow = dependencies.createWindow ?? createMainWindow;
  const backendLaunchOptions: BackendLaunchOptions = {
    client: options.client,
    proxyPort: options.proxyPort,
    webPort: options.webPort,
    workspaceDir: options.workspaceDir,
  };
  if (options.env !== undefined) {
    backendLaunchOptions.env = options.env;
  }
  const backend = launchBackend(backendLaunchOptions);

  try {
    await waitForHealth(backend, options.webPort);
  } catch (error) {
    stopBackend(backend);
    throw error;
  }

  return createWindow({
    preloadPath: options.preloadPath,
    rendererUrl: rendererUrlForPort(options.webPort),
  });
}

export function bindBackendQuitCleanup(
  appSource: AppQuitSource,
  getBackend: () => LaunchedBackendProcess | null,
  stopBackend = stopBackendProcess,
): void {
  appSource.on("before-quit", () => {
    const backend = getBackend();
    if (backend !== null) {
      stopBackend(backend);
    }
  });
}

export function showBackendStartupFailure(
  error: unknown,
  quitApp = app.quit.bind(app),
): void {
  const message = error instanceof Error ? error.message : String(error);
  dialog.showErrorBox("Transport Matters failed to start", message);
  quitApp();
}

export function registerAppLifecycle(): void {
  let backend: LaunchedBackendProcess | null = null;

  bindBackendQuitCleanup(app, () => backend);

  void app.whenReady().then(() => {
    const startupOptions = resolveBackendStartupOptions();
    void startBackendAndCreateWindow(startupOptions, {
      launchBackend: (options) => {
        backend = launchBackendProcess(options);
        return backend;
      },
    }).catch(showBackendStartupFailure);

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow({
          rendererUrl: rendererUrlForPort(startupOptions.webPort),
        });
      }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });
}

export function registerDesktopPackageSmoke(
  options: DesktopPackageSmokeOptions = {},
): void {
  const appSource = options.appSource ?? app;
  const createWindow = options.createWindow ?? createMainWindow;
  const env = options.env ?? process.env;
  const writeFile = options.writeFile ?? writeFileSync;

  void appSource.whenReady().then(() => {
    const rendererUrl = rendererUrlForPort(DEFAULT_WEB_PORT);
    createWindow({ rendererUrl });

    if (env.TRANSPORT_MATTERS_DESKTOP_SMOKE_FILE !== undefined) {
      writeFile(
        env.TRANSPORT_MATTERS_DESKTOP_SMOKE_FILE,
        JSON.stringify(
          {
            rendererUrl,
            status: "main-window-created",
          },
          null,
          2,
        ),
      );
    }

    appSource.quit();
  });
}

export function registerDesktopLifecycleFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): void {
  if (env.TRANSPORT_MATTERS_DESKTOP_PACKAGE_SMOKE === "1") {
    registerDesktopPackageSmoke({ env });
    return;
  }

  registerAppLifecycle();
}

registerDesktopLifecycleFromEnv();

function resolveBackendClient(value: string | undefined): BackendClient {
  if (value === undefined) {
    return "claude";
  }
  if (isBackendClient(value)) {
    return value;
  }
  throw new Error(
    `Unsupported Transport Matters desktop client: ${value}. Supported clients: ${SUPPORTED_BACKEND_CLIENTS.join(", ")}`,
  );
}

function resolvePort(value: string | undefined, fallback: number): number {
  if (value === undefined) {
    return fallback;
  }
  const port = Number.parseInt(value, 10);
  if (
    !Number.isInteger(port) ||
    String(port) !== value ||
    port < 1 ||
    port > 65535
  ) {
    throw new Error(`Invalid Transport Matters desktop port: ${value}`);
  }
  return port;
}
