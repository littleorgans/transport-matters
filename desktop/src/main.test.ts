import { EventEmitter } from "node:events";

import type { BrowserWindow } from "electron";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LaunchedBackendProcess } from "./backendProcess.js";

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
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:8788",
    });

    expect(browserWindowConstructor).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Transport Matters",
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          preload: "/tmp/transport-matters/preload.js",
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
        client: "codex",
        preloadPath: "/tmp/transport-matters/preload.js",
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
      client: "codex",
      proxyPort: 9900,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });
    expect(waitForHealth).toHaveBeenCalledWith(backend, 9901);
    expect(createWindow).toHaveBeenCalledWith({
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:9901/",
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
          client: "claude",
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
});
