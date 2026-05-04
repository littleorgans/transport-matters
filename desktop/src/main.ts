import { app, BrowserWindow, dialog } from "electron";
import type { BrowserWindowConstructorOptions } from "electron";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  launchBackendProcess,
  stopBackendProcess,
  watchBackendExitBeforeReady,
  type BackendClient,
  type BackendLaunchOptions,
  type LaunchedBackendProcess,
} from "./backendProcess.js";
import { waitForBackendHealth } from "./backendHealth.js";

const moduleDir = dirname(fileURLToPath(import.meta.url));

export const APP_NAME = "Transport Matters";
export const DEFAULT_PROXY_PORT = 8787;
export const DEFAULT_WEB_PORT = 8788;
export const DEFAULT_RENDERER_URL = rendererUrlForPort(DEFAULT_WEB_PORT);

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

export function resolvePreloadPath(): string {
  return join(moduleDir, "preload.js");
}

export function rendererUrlForPort(webPort: number): string {
  return `http://127.0.0.1:${webPort}`;
}

export function createWindowOptions(
  preloadPath = resolvePreloadPath(),
): BrowserWindowConstructorOptions {
  return {
    height: 900,
    minHeight: 600,
    minWidth: 900,
    show: false,
    title: APP_NAME,
    width: 1280,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: preloadPath,
      sandbox: true,
    },
  };
}

export function createMainWindow(
  options: MainWindowOptions = {},
): BrowserWindow {
  const window = new BrowserWindow(createWindowOptions(options.preloadPath));

  window.once("ready-to-show", () => {
    window.show();
  });
  void window.loadURL(options.rendererUrl ?? DEFAULT_RENDERER_URL);

  return window;
}

export function resolveBackendStartupOptions(
  env: NodeJS.ProcessEnv = process.env,
  cwd = process.cwd(),
): BackendStartupOptions {
  return {
    client: resolveBackendClient(env.TRANSPORT_MATTERS_DESKTOP_CLIENT),
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
  const backend = launchBackend({
    client: options.client,
    proxyPort: options.proxyPort,
    webPort: options.webPort,
    workspaceDir: options.workspaceDir,
  });

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

registerAppLifecycle();

function resolveBackendClient(value: string | undefined): BackendClient {
  if (value === undefined || value === "claude") {
    return "claude";
  }
  if (value === "codex") {
    return "codex";
  }
  throw new Error(`Unsupported Transport Matters desktop client: ${value}`);
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
