import { EventEmitter } from "node:events";

import type { BrowserWindow } from "electron";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { LaunchedBackendProcess } from "./backendProcess.js";
import type { PreloadProbeWindow } from "./main.js";

const browserWindowConstructor = vi.fn();
const dialogShowErrorBox = vi.fn();
const loadURL = vi.fn();
const once = vi.fn();
const setWindowOpenHandler = vi.fn();
const show = vi.fn();
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

vi.mock("electron", () => ({
  app: {
    on: vi.fn(),
    quit: vi.fn(),
    whenReady: vi.fn(() => new Promise(() => undefined)),
  },
  BrowserWindow: vi.fn(function BrowserWindow(
    options: Record<string, unknown>,
  ) {
    browserWindowConstructor(options);
    return {
      loadURL,
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

describe("desktop main process", () => {
  beforeEach(() => {
    browserWindowConstructor.mockClear();
    dialogShowErrorBox.mockClear();
    loadURL.mockClear();
    once.mockClear();
    setWindowOpenHandler.mockClear();
    show.mockClear();
    webContentsOn.mockClear();
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
      ),
    ).toEqual({
      env: { TRANSPORT_MATTERS_DESKTOP_CLIENT: "gemini" },
      proxyPort: 8787,
      webPort: 8788,
      workspaceDir: "/tmp/workspace",
    });
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
    const createWindow = vi.fn(
      () => ({ loadURL, once, show }) as unknown as BrowserWindow,
    );
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
