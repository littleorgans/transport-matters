import { app, BrowserWindow, dialog, type WebContents } from "electron";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  launchBackendProcess,
  stopBackendProcess,
  watchBackendExitBeforeReady,
  type BackendLaunchOptions,
  type LaunchedBackendProcess,
} from "./backendProcess.js";
import {
  backendHealthUrl,
  isBackendHealthy,
  waitForBackendHealth,
} from "./backendHealth.js";
import {
  ENV,
  resolveDesktopChannelSpec,
  type DesktopChannelSpec,
} from "./env.js";
import {
  APP_NAME,
  DEFAULT_WEB_PORT,
  createHostedWindow,
  createWindowOptions,
  rendererUrlForPort,
} from "./window.js";

const moduleDir = dirname(fileURLToPath(import.meta.url));

const DEFAULT_PROXY_PORT = 8787;
const HOSTED_BACKEND_FAILURE_LIMIT = 3;
const HOSTED_BACKEND_POLL_GAP_MS = 1_000;
const PREVIEW_AMBER_ICON = join(moduleDir, "../assets/preview-amber.png");

export interface MainWindowOptions {
  icon?: string;
  preloadPath?: string;
  rendererUrl?: string;
  title?: string;
}

export interface BackendStartupOptions extends BackendLaunchOptions {
  icon?: string;
  preloadPath?: string;
  title?: string;
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

export interface AppIdentitySource {
  dock?: {
    setIcon(icon: string): void;
  };
  setAppUserModelId(id: string): void;
  setName(name: string): void;
  setPath(name: "userData", path: string): void;
}

export interface AppliedChannelIdentity {
  icon?: string;
  title: string;
}

export interface AppLifecycleOptions {
  channelSpec?: DesktopChannelSpec;
  env?: NodeJS.ProcessEnv;
  icon?: string;
  title?: string;
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
  icon?: string;
  probeBackendHealth?: HostedBackendHealthProbe;
  routeUrl: string;
  title?: string;
}

export type HostedBackendHealthProbe = (healthUrl: string) => Promise<boolean>;

interface HostedWindowLifecycleOptions {
  quitOnWindowAllClosed?: boolean;
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
    icon: options.icon,
    preloadPath: options.preloadPath ?? resolvePreloadPath(),
    rendererUrl: options.rendererUrl,
    title: options.title,
  });
}

export function applyChannelIdentity(
  appSource: AppIdentitySource,
  spec: DesktopChannelSpec,
): AppliedChannelIdentity {
  appSource.setName(spec.electron.appName);
  appSource.setAppUserModelId(spec.electron.appId);
  if (spec.electron.userDataDir !== null) {
    appSource.setPath(
      "userData",
      join(spec.home, spec.electron.userDataDir),
    );
  }
  const icon = resolveChannelIcon(spec);
  if (icon !== undefined) {
    appSource.dock?.setIcon(icon);
  }
  return { icon, title: spec.electron.appName };
}

export function resolveBackendStartupOptions(
  env: NodeJS.ProcessEnv = process.env,
  cwd = process.cwd(),
  spec: DesktopChannelSpec = resolveDesktopChannelSpec(env),
): BackendStartupOptions {
  return {
    env: { ...env, [ENV.CHANNEL]: spec.id },
    proxyPort: resolvePort(env[ENV.PROXY_PORT], spec.proxyPort),
    webPort: resolvePort(env[ENV.WEB_PORT], spec.webPort),
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

  return createWindow(
    buildMainWindowOptions({
      icon: options.icon,
      preloadPath: options.preloadPath,
      rendererUrl: rendererUrlForPort(options.webPort),
      title: options.title,
    }),
  );
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
  windowOptions: Pick<MainWindowOptions, "icon" | "title"> = {},
  lifecycleOptions: HostedWindowLifecycleOptions = {},
): void {
  appSource.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow({ ...windowOptions, rendererUrl });
    }
  });

  appSource.on("window-all-closed", () => {
    if (
      lifecycleOptions.quitOnWindowAllClosed === true ||
      process.platform !== "darwin"
    ) {
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

export function registerAppLifecycle(options: AppLifecycleOptions = {}): void {
  let backend: LaunchedBackendProcess | null = null;
  const env = options.env ?? process.env;
  const channelSpec = options.channelSpec ?? resolveDesktopChannelSpec(env);

  bindBackendQuitCleanup(app, () => backend);

  void app.whenReady().then(() => {
    const startupOptions = resolveBackendStartupOptions(
      env,
      process.cwd(),
      channelSpec,
    );
    startupOptions.icon = options.icon;
    startupOptions.title = options.title;
    const rendererUrl = rendererUrlForPort(startupOptions.webPort);
    void startBackendAndCreateWindow(startupOptions, {
      launchBackend: (options) => {
        backend = launchBackendProcess(options);
        return backend;
      },
      }).catch(showBackendStartupFailure);

    bindHostedWindowLifecycle(
      app,
      rendererUrl,
      createMainWindow,
      buildMainWindowOptions({
        icon: options.icon,
        title: options.title,
      }),
    );
  });
}

export function registerHostedDesktopLifecycle(
  options: HostedDesktopLifecycleOptions,
): void {
  const appSource = options.appSource ?? app;
  const createWindow = options.createWindow ?? createMainWindow;
  const healthUrl = hostedRouteHealthUrl(options.routeUrl);
  const probeBackendHealth =
    options.probeBackendHealth ??
    ((targetHealthUrl: string) => isBackendHealthy(targetHealthUrl));
  const quitHostedApp = appSource.quit.bind(appSource);
  const createWindowWithLiveness = (
    windowOptions: MainWindowOptions,
  ): BrowserWindow => {
    const window = createWindow(windowOptions);
    if (healthUrl !== null) {
      registerHostedBackendLivenessPoll(
        window,
        healthUrl,
        probeBackendHealth,
        quitHostedApp,
      );
    }
    return window;
  };

  void appSource.whenReady().then(() => {
    createWindowWithLiveness(
      buildMainWindowOptions({
        icon: options.icon,
        rendererUrl: options.routeUrl,
        title: options.title,
      }),
    );
  });
  bindHostedWindowLifecycle(
    appSource,
    options.routeUrl,
    createWindowWithLiveness,
    buildMainWindowOptions({
      icon: options.icon,
      title: options.title,
    }),
    { quitOnWindowAllClosed: true },
  );
}

function registerHostedBackendLivenessPoll(
  window: BrowserWindow,
  healthUrl: string,
  probeBackendHealth: HostedBackendHealthProbe,
  quitHostedApp: () => void,
): void {
  let consecutiveFailures = 0;
  let hasClosed = false;
  let hasLoaded = false;
  let pendingTimeout: ReturnType<typeof setTimeout> | undefined;

  const clearPendingTimeout = (): void => {
    if (pendingTimeout !== undefined) {
      clearTimeout(pendingTimeout);
      pendingTimeout = undefined;
    }
  };

  const scheduleNextProbe = (): void => {
    if (hasClosed) {
      return;
    }
    clearPendingTimeout();
    pendingTimeout = setTimeout(() => {
      pendingTimeout = undefined;
      void runProbe();
    }, HOSTED_BACKEND_POLL_GAP_MS);
  };

  const runProbe = async (): Promise<void> => {
    if (hasClosed) {
      return;
    }

    let isHealthy = false;
    try {
      isHealthy = await probeBackendHealth(healthUrl);
    } catch {
      isHealthy = false;
    }

    if (hasClosed) {
      return;
    }

    consecutiveFailures = isHealthy ? 0 : consecutiveFailures + 1;
    if (consecutiveFailures >= HOSTED_BACKEND_FAILURE_LIMIT) {
      quitHostedApp();
      return;
    }
    scheduleNextProbe();
  };

  window.webContents.on("did-finish-load", () => {
    if (hasLoaded) {
      return;
    }
    hasLoaded = true;
    void runProbe();
  });

  window.on("closed", () => {
    hasClosed = true;
    clearPendingTimeout();
  });
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
  const channelSpec = resolveDesktopChannelSpec(env);
  const identity = applyChannelIdentity(app, channelSpec);

  if (env[ENV.DESKTOP_PACKAGE_SMOKE] === "1") {
    registerDesktopPackageSmoke({ env });
    return;
  }

  const routeUrl = env[ENV.DESKTOP_ROUTE_URL];
  if (routeUrl !== undefined) {
    registerHostedDesktopLifecycle({
      icon: identity.icon,
      routeUrl,
      title: identity.title,
    });
    return;
  }

  registerAppLifecycle({
    channelSpec,
    env,
    icon: identity.icon,
    title: identity.title,
  });
}

registerDesktopLifecycleFromEnv();

function hostedRouteHealthUrl(routeUrl: string): string | null {
  let parsedRouteUrl: URL;
  try {
    parsedRouteUrl = new URL(routeUrl);
  } catch {
    return null;
  }

  if (parsedRouteUrl.port === "") {
    return null;
  }

  const webPort = Number(parsedRouteUrl.port);
  if (!Number.isInteger(webPort) || webPort <= 0 || webPort > 65_535) {
    return null;
  }

  return backendHealthUrl(webPort);
}

function resolveChannelIcon(spec: DesktopChannelSpec): string | undefined {
  return spec.electron.dockIcon === "preview-amber"
    ? PREVIEW_AMBER_ICON
    : undefined;
}

function buildMainWindowOptions(options: MainWindowOptions): MainWindowOptions {
  const result: MainWindowOptions = {};
  if (options.icon !== undefined) {
    result.icon = options.icon;
  }
  if (options.preloadPath !== undefined) {
    result.preloadPath = options.preloadPath;
  }
  if (options.rendererUrl !== undefined) {
    result.rendererUrl = options.rendererUrl;
  }
  if (options.title !== undefined) {
    result.title = options.title;
  }
  return result;
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
