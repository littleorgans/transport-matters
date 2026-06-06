import { app, BrowserWindow, dialog, type WebContents } from "electron";
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
import { ENV } from "./env.js";
import {
  APP_NAME,
  DEFAULT_WEB_PORT,
  createHostedWindow,
  createWindowOptions,
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

export interface AppWindowLifecycleSource extends AppReadySource {
  on(event: "activate" | "window-all-closed", listener: () => void): void;
}

export interface DesktopPackageSmokeOptions {
  appSource?: AppReadySource;
  createProbeWindow?: () => PreloadProbeWindow;
  env?: NodeJS.ProcessEnv;
  writeFile?: (path: string, data: string) => void;
}

export interface HostedDesktopLifecycleOptions {
  appSource?: AppWindowLifecycleSource;
  createWindow?: (options: MainWindowOptions) => BrowserWindow;
  routeUrl: string;
}

export function resolvePreloadPath(): string {
  // CommonJS: sandboxed Electron preloads are evaluated as CommonJS, so the
  // build emits `preload.cjs` (from `src/preload.cts`) even though this package
  // is `"type": "module"`. Pointing at `preload.js` would load an ESM file and
  // throw "Cannot use import statement outside a module" at preload time.
  return join(moduleDir, "preload.cjs");
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
    client: resolveBackendClient(env[ENV.DESKTOP_CLIENT]),
    env: { ...env },
    proxyPort: resolvePort(env[ENV.PROXY_PORT], DEFAULT_PROXY_PORT),
    webPort: resolvePort(env[ENV.WEB_PORT], DEFAULT_WEB_PORT),
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

export function bindHostedWindowLifecycle(
  appSource: AppWindowLifecycleSource,
  rendererUrl: string,
  createWindow: (options: MainWindowOptions) => BrowserWindow = createMainWindow,
): void {
  appSource.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow({ rendererUrl });
    }
  });

  appSource.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      appSource.quit();
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
    const rendererUrl = rendererUrlForPort(startupOptions.webPort);
    void startBackendAndCreateWindow(startupOptions, {
      launchBackend: (options) => {
        backend = launchBackendProcess(options);
        return backend;
      },
    }).catch(showBackendStartupFailure);

    bindHostedWindowLifecycle(app, rendererUrl);
  });
}

export function registerHostedDesktopLifecycle(
  options: HostedDesktopLifecycleOptions,
): void {
  const appSource = options.appSource ?? app;
  const createWindow = options.createWindow ?? createMainWindow;

  void appSource.whenReady().then(() => {
    createWindow({ rendererUrl: options.routeUrl });
  });
  bindHostedWindowLifecycle(appSource, options.routeUrl, createWindow);
}

/**
 * Key the preload exposes on the renderer's main world via
 * `contextBridge.exposeInMainWorld`. The package smoke reads it back to prove
 * the preload actually executed inside a real (sandboxed) renderer.
 */
export const DESKTOP_PRELOAD_BRIDGE_KEY = "transportMattersDesktop";

/** Fail-closed ceiling for the preload probe so the smoke can never hang CI. */
export const DESKTOP_PRELOAD_PROBE_TIMEOUT_MS = 10_000;

export type DesktopSmokeStatus =
  | "main-window-created"
  | "preload-error"
  | "preload-bridge-missing"
  | "preload-timeout";

export interface PreloadProbeWindow {
  loadURL(url: string): Promise<void>;
  webContents: WebContents;
}

/**
 * Resolve the outcome of loading the sandboxed preload in a real renderer.
 *
 * A preload load failure is non-fatal in Electron (the window still opens), so
 * "a window was created" proves nothing. This watches the renderer directly:
 * `preload-error` means the preload threw (e.g. an ESM `import` in a CommonJS
 * sandboxed preload); on a successful load the exposed bridge is read back to
 * prove `contextBridge.exposeInMainWorld` ran. Anything else fails closed.
 */
export function awaitPreloadSmokeStatus(
  webContents: WebContents,
  timeoutMs: number = DESKTOP_PRELOAD_PROBE_TIMEOUT_MS,
): Promise<DesktopSmokeStatus> {
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      settle("preload-timeout");
    }, timeoutMs);

    function settle(status: DesktopSmokeStatus): void {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(status);
    }

    webContents.on("preload-error", () => {
      settle("preload-error");
    });

    webContents.on("did-finish-load", () => {
      void webContents
        .executeJavaScript(
          `globalThis.${DESKTOP_PRELOAD_BRIDGE_KEY}?.appName ?? null`,
        )
        .then((appName: unknown) => {
          settle(
            appName === APP_NAME
              ? "main-window-created"
              : "preload-bridge-missing",
          );
        })
        .catch(() => {
          settle("preload-bridge-missing");
        });
    });
  });
}

/**
 * Hidden window that loads the real sandboxed preload against `about:blank`.
 * `about:blank` always commits, so the preload runs deterministically without a
 * running backend and without tripping the hosted-window `did-fail-load` error
 * dialog, which would block a headless CI run.
 */
export function createPreloadProbeWindow(): BrowserWindow {
  return new BrowserWindow(createWindowOptions(resolvePreloadPath()));
}

export function registerDesktopPackageSmoke(
  options: DesktopPackageSmokeOptions = {},
): void {
  const appSource = options.appSource ?? app;
  const createProbeWindow =
    options.createProbeWindow ?? createPreloadProbeWindow;
  const env = options.env ?? process.env;
  const writeFile = options.writeFile ?? writeFileSync;

  void appSource.whenReady().then(async () => {
    const probe = createProbeWindow();
    const statusPromise = awaitPreloadSmokeStatus(probe.webContents);
    void probe.loadURL("about:blank");
    const status = await statusPromise;

    const smokeFile = env[ENV.DESKTOP_SMOKE_FILE];
    if (smokeFile !== undefined) {
      writeFile(
        smokeFile,
        JSON.stringify(
          {
            status,
            url: "about:blank",
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
  if (env[ENV.DESKTOP_PACKAGE_SMOKE] === "1") {
    registerDesktopPackageSmoke({ env });
    return;
  }

  const routeUrl = env[ENV.DESKTOP_ROUTE_URL];
  if (routeUrl !== undefined) {
    registerHostedDesktopLifecycle({ routeUrl });
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
