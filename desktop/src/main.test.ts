import { EventEmitter } from "node:events";
import { join } from "node:path";

import type { BrowserWindow } from "electron";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import type { LaunchedBackendProcess } from "./backendProcess.js";
import type { PreloadProbeWindow } from "./main.js";

const browserWindowConstructor = vi.fn();
const dialogShowErrorBox = vi.fn();
const loadURL = vi.fn();
const once = vi.fn();
const appOn = vi.fn();
const appQuit = vi.fn();
const appWhenReady = vi.fn(() => new Promise(() => undefined));
const setAppUserModelId = vi.fn();
const setDockIcon = vi.fn();
const setName = vi.fn();
const setPath = vi.fn();
const setWindowOpenHandler = vi.fn();
const show = vi.fn();
const windowOn = vi.fn();
const webContentsOn = vi.fn();

function createBackendFixture(): LaunchedBackendProcess {
  const child = Object.assign(new EventEmitter(), {
    kill: vi.fn(() => true),
  });

  return {
    child,
    launch: {
      args: [],
      command: "transport-matters",
      cwd: "/tmp/workspace",
      env: {},
    },
  };
}

function createLiveRuntimeStatus(cwd = process.cwd()) {
  return {
    channel: "stable",
    cwd,
    defaultRouteUrl: null,
    proxyPort: 9900,
    state: "live" as const,
    webPort: 9901,
  };
}

vi.mock("electron", () => ({
  app: {
    dock: {
      setIcon: setDockIcon,
    },
    on: appOn,
    quit: appQuit,
    setAppUserModelId,
    setName,
    setPath,
    whenReady: appWhenReady,
  },
  BrowserWindow: vi.fn(function BrowserWindow(
    options: Record<string, unknown>,
  ) {
    browserWindowConstructor(options);
    return {
      loadURL,
      on: windowOn,
      once,
      show,
      webContents: {
        on: webContentsOn,
        setWindowOpenHandler,
      },
    };
  }),
  dialog: {
    showErrorBox: dialogShowErrorBox,
  },
}));

async function flushMicrotasks(turns = 3): Promise<void> {
  for (let index = 0; index < turns; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

async function flushPromiseQueue(turns = 3): Promise<void> {
  for (let index = 0; index < turns; index += 1) {
    await Promise.resolve();
  }
}

function withProcessPlatform<T>(platform: NodeJS.Platform, run: () => T): T {
  const descriptor = Object.getOwnPropertyDescriptor(process, "platform");
  Object.defineProperty(process, "platform", { value: platform });
  try {
    return run();
  } finally {
    if (descriptor) {
      Object.defineProperty(process, "platform", descriptor);
    }
  }
}

interface ProbeFixture {
  window: PreloadProbeWindow;
  handlers: Map<string, (...args: unknown[]) => void>;
  loadURL: Mock;
  executeJavaScript: Mock;
}

function createProbeFixture(
  executeJavaScript: Mock = vi.fn(async () => "Transport Matters"),
): ProbeFixture {
  const handlers = new Map<string, (...args: unknown[]) => void>();
  const on = vi.fn((event: string, listener: (...args: unknown[]) => void) => {
    handlers.set(event, listener);
  });
  const loadURL = vi.fn(async () => undefined);
  const window = {
    loadURL,
    webContents: { on, executeJavaScript },
  } as unknown as PreloadProbeWindow;
  return { window, handlers, loadURL, executeJavaScript };
}

interface HostedWindowFixture {
  close: Mock;
  webContentsHandlers: Map<string, (...args: unknown[]) => void>;
  window: BrowserWindow;
  windowHandlers: Map<string, (...args: unknown[]) => void>;
}

function createHostedWindowFixture(): HostedWindowFixture {
  const webContentsHandlers = new Map<string, (...args: unknown[]) => void>();
  const windowHandlers = new Map<string, (...args: unknown[]) => void>();
  const close = vi.fn();
  const window = {
    close,
    loadURL: vi.fn(async () => undefined),
    on: vi.fn((event: string, listener: (...args: unknown[]) => void) => {
      windowHandlers.set(event, listener);
    }),
    once,
    show,
    webContents: {
      on: vi.fn((event: string, listener: (...args: unknown[]) => void) => {
        webContentsHandlers.set(event, listener);
      }),
      setWindowOpenHandler,
    },
  } as unknown as BrowserWindow;

  return { close, webContentsHandlers, window, windowHandlers };
}

interface RegisteredHostedLifecycleFixture extends HostedWindowFixture {
  appHandlers: Map<string, () => void>;
  createWindow: Mock;
  quit: Mock;
  probeBackendHealth: Mock;
}

async function registerHostedLifecycleFixture(
  probeBackendHealth: Mock = vi.fn(async () => true),
): Promise<RegisteredHostedLifecycleFixture> {
  const fixture = createHostedWindowFixture();
  const appHandlers = new Map<string, () => void>();
  const createWindow = vi.fn(() => fixture.window);
  const quit = vi.fn();
  const whenReady = vi.fn(async () => undefined);
  const on = vi.fn((event: string, listener: () => void) => {
    appHandlers.set(event, listener);
  });

  const { registerHostedDesktopLifecycle } = await import("./main.js");

  registerHostedDesktopLifecycle({
    appSource: { on, quit, whenReady },
    createWindow,
    probeBackendHealth,
    routeUrl: "http://127.0.0.1:9901/canvas",
  });
  await flushPromiseQueue();

  return { ...fixture, appHandlers, createWindow, probeBackendHealth, quit };
}

describe("desktop main process", () => {
  beforeEach(() => {
    appOn.mockReset();
    appQuit.mockClear();
    appWhenReady.mockReset();
    appWhenReady.mockImplementation(() => new Promise(() => undefined));
    browserWindowConstructor.mockClear();
    dialogShowErrorBox.mockClear();
    loadURL.mockClear();
    once.mockClear();
    setAppUserModelId.mockClear();
    setDockIcon.mockClear();
    setName.mockClear();
    setPath.mockClear();
    setWindowOpenHandler.mockClear();
    show.mockClear();
    windowOn.mockClear();
    webContentsOn.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates a secure BrowserWindow for the hosted web app", async () => {
    const { createMainWindow } = await import("./main.js");

    createMainWindow({
      preloadPath: "/tmp/transport-matters/preload.cjs",
      rendererUrl: "http://127.0.0.1:8788",
    });

    expect(browserWindowConstructor).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Transport Matters",
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          preload: "/tmp/transport-matters/preload.cjs",
          sandbox: true,
        },
      }),
    );
    expect(loadURL).toHaveBeenCalledWith("http://127.0.0.1:8788/");
  });

  it("waits for backend health before loading the hosted web app", async () => {
    const events: string[] = [];
    const backend = createBackendFixture();
    const launchBackend = vi.fn(() => {
      events.push("launch");
      return backend;
    });
    const waitForHealth = vi.fn(async () => {
      events.push("health");
    });
    const createWindow = vi.fn(() => {
      events.push("window");
      return { loadURL, once, show } as unknown as BrowserWindow;
    });

    const { startBackendAndCreateWindow } = await import("./main.js");

    await startBackendAndCreateWindow(
      {
        preloadPath: "/tmp/transport-matters/preload.cjs",
        proxyPort: 9900,
        webPort: 9901,
        workspaceDir: "/tmp/workspace",
      },
      {
        createWindow,
        launchBackend,
        waitForHealth,
      },
    );

    expect(events).toEqual(["launch", "health", "window"]);
    expect(launchBackend).toHaveBeenCalledWith({
      proxyPort: 9900,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });
    expect(waitForHealth).toHaveBeenCalledWith(backend, 9901);
    expect(createWindow).toHaveBeenCalledWith({
      preloadPath: "/tmp/transport-matters/preload.cjs",
      rendererUrl: "http://127.0.0.1:9901/canvas",
    });
  });

  it("preserves inherited environment for the backend startup path", async () => {
    const backend = createBackendFixture();
    const createWindow = vi.fn(
      () => ({ loadURL, once, show }) as unknown as BrowserWindow,
    );
    const launchBackend = vi.fn(() => backend);
    const waitForHealth = vi.fn(async () => undefined);

    const { resolveBackendStartupOptions, startBackendAndCreateWindow } =
      await import("./main.js");

    const startupOptions = resolveBackendStartupOptions(
      {
        CLAUDE_CONFIG_DIR: "/tmp/claude",
        PATH: "/usr/local/bin:/usr/bin",
        TRANSPORT_MATTERS_DESKTOP_CLIENT: "claude",
        TRANSPORT_MATTERS_PROXY_PORT: "9900",
        TRANSPORT_MATTERS_WEB_PORT: "9901",
      },
      "/tmp/workspace",
      undefined,
      { runtimeStatus: null },
    );

    await startBackendAndCreateWindow(startupOptions, {
      createWindow,
      launchBackend,
      waitForHealth,
    });

    expect(launchBackend).toHaveBeenCalledWith({
      env: {
        CLAUDE_CONFIG_DIR: "/tmp/claude",
        PATH: "/usr/local/bin:/usr/bin",
        TRANSPORT_MATTERS_CHANNEL: "stable",
        TRANSPORT_MATTERS_DESKTOP_CLIENT: "claude",
        TRANSPORT_MATTERS_PROXY_PORT: "9900",
        TRANSPORT_MATTERS_WEB_PORT: "9901",
      },
      proxyPort: 9900,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });
  });

  it("ignores desktop client selection for backend startup", async () => {
    const { resolveBackendStartupOptions } = await import("./main.js");

    expect(
      resolveBackendStartupOptions(
        { TRANSPORT_MATTERS_DESKTOP_CLIENT: "gemini" },
        "/tmp/workspace",
        undefined,
        { runtimeStatus: null },
      ),
    ).toEqual({
      env: {
        TRANSPORT_MATTERS_CHANNEL: "stable",
        TRANSPORT_MATTERS_DESKTOP_CLIENT: "gemini",
      },
      proxyPort: 8787,
      webPort: 8788,
      workspaceDir: "/tmp/workspace",
    });
  });

  it("prefers live runtime ports while preserving explicit pins", async () => {
    const { resolveBackendStartupOptions } = await import("./main.js");

    expect(
      resolveBackendStartupOptions(
        { TRANSPORT_MATTERS_PROXY_PORT: "9910" },
          "/tmp/workspace",
          undefined,
          { runtimeStatus: createLiveRuntimeStatus("/tmp/workspace") },
      ),
    ).toEqual({
      env: {
        TRANSPORT_MATTERS_CHANNEL: "stable",
        TRANSPORT_MATTERS_PROXY_PORT: "9910",
      },
      proxyPort: 9910,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });
  });

  it("applies preview channel identity before readiness", async () => {
    const appSource = {
      dock: { setIcon: setDockIcon },
      setAppUserModelId,
      setName,
      setPath,
    };
    const { applyChannelIdentity } = await import("./main.js");

    const identity = applyChannelIdentity(appSource, {
      badge: { color: "amber", hex: "#f59e0b", text: "PREVIEW" },
      databaseName: "transport_matters_preview",
      home: "/tmp/transport-matters-preview",
      id: "preview",
      label: "Preview",
      proxyPort: 8797,
      webPort: 8798,
      electron: {
        appId: "io.helioy.transport-matters.preview",
        appName: "Transport Matters Preview",
        dockIcon: "preview-amber",
        userDataDir: "electron-user-data",
      },
    });

    expect(setName).toHaveBeenCalledWith("Transport Matters Preview");
    expect(setAppUserModelId).toHaveBeenCalledWith(
      "io.helioy.transport-matters.preview",
    );
    expect(setPath).toHaveBeenCalledWith(
      "userData",
      join("/tmp/transport-matters-preview", "electron-user-data"),
    );
    expect(identity.title).toBe("Transport Matters Preview");
    expect(identity.icon).toMatch(/assets[/\\]preview-amber\.png$/);
    expect(setDockIcon).toHaveBeenCalledWith(identity.icon);
  });

  it("shows a clear startup error when backend readiness fails", async () => {
    const backend = createBackendFixture();
    const appQuit = vi.fn();
    const createWindow = vi.fn();
    const launchBackend = vi.fn(() => backend);
    const stopBackend = vi.fn();
    const waitForHealth = vi.fn(async () => {
      throw new Error("Transport Matters backend exited before readiness.");
    });

    const { showBackendStartupFailure, startBackendAndCreateWindow } =
      await import("./main.js");

    await expect(
      startBackendAndCreateWindow(
        {
          proxyPort: 9900,
          webPort: 9901,
          workspaceDir: "/tmp/workspace",
        },
        {
          createWindow,
          launchBackend,
          stopBackend,
          waitForHealth,
        },
      ),
    ).rejects.toThrow("Transport Matters backend exited before readiness.");

    expect(stopBackend).toHaveBeenCalledWith(backend);
    expect(createWindow).not.toHaveBeenCalled();

    showBackendStartupFailure(
      new Error("Transport Matters backend exited before readiness."),
      appQuit,
    );

    expect(dialogShowErrorBox).toHaveBeenCalledWith(
      "Transport Matters failed to start",
      "Transport Matters backend exited before readiness.",
    );
    expect(appQuit).toHaveBeenCalled();
  });

  it("terminates the launched backend when the app quits", async () => {
    const backend = createBackendFixture();
    const on = vi.fn((_event: string, handler: () => void) => {
      handler();
    });
    const stopBackend = vi.fn();

    const { bindBackendQuitCleanup } = await import("./main.js");

    bindBackendQuitCleanup({ on }, () => backend, stopBackend);

    expect(on).toHaveBeenCalledWith("before-quit", expect.any(Function));
    expect(stopBackend).toHaveBeenCalledWith(backend);
  });

  it("opens a Python supplied hosted route without backend startup", async () => {
    const fixture = createHostedWindowFixture();
    const createWindow = vi.fn(() => fixture.window);
    const quit = vi.fn();
    const whenReady = vi.fn(async () => undefined);
    const on = vi.fn();

    const { registerHostedDesktopLifecycle } = await import("./main.js");

    registerHostedDesktopLifecycle({
      appSource: { on, quit, whenReady },
      createWindow,
      routeUrl: "http://127.0.0.1:9901/canvas",
    });
    await new Promise((resolve) => setImmediate(resolve));

    expect(createWindow).toHaveBeenCalledWith({
      rendererUrl: "http://127.0.0.1:9901/canvas",
    });
    expect(on).toHaveBeenCalledWith("activate", expect.any(Function));
    expect(on).toHaveBeenCalledWith("window-all-closed", expect.any(Function));
  });

  it("opens a live discovered runtime without backend startup", async () => {
    const { registerDesktopLifecycleFromEnv } = await import("./main.js");

    appWhenReady.mockResolvedValue(undefined);
    registerDesktopLifecycleFromEnv({}, {
      readRuntimeStatus: () => createLiveRuntimeStatus(),
    });
    await flushPromiseQueue();

    expect(loadURL).toHaveBeenCalledWith("http://127.0.0.1:9901/canvas");
    expect(appOn.mock.calls.map(([event]) => event)).toEqual(
      expect.arrayContaining(["activate", "window-all-closed"]),
    );
  });

  it("quits the hosted app when the only hosted window closes on darwin", async () => {
    const fixture = await registerHostedLifecycleFixture();

    withProcessPlatform("darwin", () => {
      fixture.appHandlers.get("window-all-closed")?.();
    });

    expect(fixture.quit).toHaveBeenCalledOnce();
  });

  it("keeps the foreground window-all-closed default unchanged on darwin", async () => {
    const appHandlers = new Map<string, () => void>();
    const on = vi.fn((event: string, listener: () => void) => {
      appHandlers.set(event, listener);
    });
    const quit = vi.fn();

    const { bindHostedWindowLifecycle } = await import("./main.js");

    bindHostedWindowLifecycle(
      { on, quit, whenReady: vi.fn(async () => undefined) },
      "http://127.0.0.1:9901/canvas",
      vi.fn(),
    );

    withProcessPlatform("darwin", () => {
      appHandlers.get("window-all-closed")?.();
    });

    expect(quit).not.toHaveBeenCalled();
  });

  it("does not poll hosted backend liveness before the first successful load", async () => {
    vi.useFakeTimers();
    const probeBackendHealth = vi.fn(async () => true);
    const fixture = await registerHostedLifecycleFixture(probeBackendHealth);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(probeBackendHealth).not.toHaveBeenCalled();

    fixture.webContentsHandlers.get("did-finish-load")?.();
    await flushPromiseQueue();

    expect(probeBackendHealth).toHaveBeenCalledOnce();
    expect(probeBackendHealth).toHaveBeenCalledWith(
      "http://127.0.0.1:9901/health",
    );
    expect(fixture.close).not.toHaveBeenCalled();
  });

  it("keeps a hosted window open when transient liveness failures recover", async () => {
    vi.useFakeTimers();
    const probeBackendHealth = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(false);
    const fixture = await registerHostedLifecycleFixture(probeBackendHealth);

    fixture.webContentsHandlers.get("did-finish-load")?.();
    await flushPromiseQueue();
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(1_000);

    expect(probeBackendHealth).toHaveBeenCalledTimes(5);
    expect(fixture.close).not.toHaveBeenCalled();
    expect(fixture.quit).not.toHaveBeenCalled();
  });

  it("quits the hosted app after three consecutive failed liveness probes", async () => {
    vi.useFakeTimers();
    const probeBackendHealth = vi.fn(async () => false);
    const fixture = await registerHostedLifecycleFixture(probeBackendHealth);

    fixture.webContentsHandlers.get("did-finish-load")?.();
    await flushPromiseQueue();
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(1_000);

    expect(probeBackendHealth).toHaveBeenCalledTimes(3);
    expect(fixture.quit).toHaveBeenCalledOnce();
    expect(fixture.close).not.toHaveBeenCalled();
  });

  it("clears the hosted liveness timeout when the window closes", async () => {
    vi.useFakeTimers();
    const probeBackendHealth = vi.fn(async () => false);
    const fixture = await registerHostedLifecycleFixture(probeBackendHealth);

    fixture.webContentsHandlers.get("did-finish-load")?.();
    await flushPromiseQueue();
    fixture.windowHandlers.get("closed")?.();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(probeBackendHealth).toHaveBeenCalledOnce();
    expect(fixture.close).not.toHaveBeenCalled();
    expect(fixture.quit).not.toHaveBeenCalled();
  });

  it("records package smoke readiness after the preload executes", async () => {
    const fixture = createProbeFixture();
    const createProbeWindow = vi.fn(() => fixture.window);
    const quit = vi.fn();
    const whenReady = vi.fn(async () => undefined);
    const writeFile = vi.fn();

    const { registerDesktopPackageSmoke } = await import("./main.js");

    registerDesktopPackageSmoke({
      appSource: { quit, whenReady },
      createProbeWindow,
      env: {
        TRANSPORT_MATTERS_DESKTOP_SMOKE_FILE: "/tmp/desktop-smoke.json",
      },
      writeFile,
    });

    await flushMicrotasks();
    fixture.handlers.get("did-finish-load")?.();
    await flushMicrotasks();

    expect(createProbeWindow).toHaveBeenCalledOnce();
    expect(fixture.loadURL).toHaveBeenCalledWith("about:blank");
    expect(writeFile).toHaveBeenCalledWith(
      "/tmp/desktop-smoke.json",
      expect.stringContaining('"status": "main-window-created"'),
    );
    expect(quit).toHaveBeenCalled();
  });
});

describe("desktop preload smoke probe", () => {
  it("reports success when the preload exposes the bridge", async () => {
    const { awaitPreloadSmokeStatus } = await import("./main.js");
    const fixture = createProbeFixture();

    const statusPromise = awaitPreloadSmokeStatus(
      fixture.window.webContents,
      1000,
    );
    fixture.handlers.get("did-finish-load")?.();

    expect(await statusPromise).toBe("main-window-created");
    expect(fixture.executeJavaScript).toHaveBeenCalled();
  });

  it("reports preload-error when the sandboxed preload throws", async () => {
    const { awaitPreloadSmokeStatus } = await import("./main.js");
    const fixture = createProbeFixture();

    const statusPromise = awaitPreloadSmokeStatus(
      fixture.window.webContents,
      1000,
    );
    fixture.handlers.get("preload-error")?.();

    expect(await statusPromise).toBe("preload-error");
  });

  it("reports preload-bridge-missing when the bridge is absent after load", async () => {
    const { awaitPreloadSmokeStatus } = await import("./main.js");
    const fixture = createProbeFixture(vi.fn(async () => null));

    const statusPromise = awaitPreloadSmokeStatus(
      fixture.window.webContents,
      1000,
    );
    fixture.handlers.get("did-finish-load")?.();

    expect(await statusPromise).toBe("preload-bridge-missing");
  });
});
