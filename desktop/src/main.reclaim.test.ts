import { EventEmitter } from "node:events";

import { beforeEach, describe, expect, it, vi } from "vitest";

const appOn = vi.fn();
const appQuit = vi.fn();
const appWhenReady = vi.fn(() => new Promise(() => undefined));
const browserWindowConstructor = vi.fn();
const loadURL = vi.fn();
const once = vi.fn();
const setAppUserModelId = vi.fn();
const setDockIcon = vi.fn();
const setName = vi.fn();
const setPath = vi.fn();
const setWindowOpenHandler = vi.fn();
const show = vi.fn();
const windowOn = vi.fn();
const webContentsOn = vi.fn();
const waitForBackendHealth = vi.fn(async () => undefined);

const backendChild = Object.assign(new EventEmitter(), {
  kill: vi.fn(() => true),
});
const launchBackendProcess = vi.fn(() => ({
  child: backendChild,
  launch: {
    args: [],
    command: "transport-matters",
    cwd: "/tmp/workspace",
    env: {},
  },
}));
const stopBackendProcess = vi.fn();
const watchBackendExitBeforeReady = vi.fn(() => ({
  cancel: vi.fn(),
  promise: new Promise<never>(() => undefined),
}));

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
    showErrorBox: vi.fn(),
  },
}));

vi.mock("./backendHealth.js", () => ({
  backendHealthUrl: (port: number) => `http://127.0.0.1:${port}/health`,
  isBackendHealthy: vi.fn(async () => true),
  waitForBackendHealth,
}));

vi.mock("./backendProcess.js", () => ({
  launchBackendProcess,
  stopBackendProcess,
  watchBackendExitBeforeReady,
}));

async function flushPromiseQueue(turns = 3): Promise<void> {
  for (let index = 0; index < turns; index += 1) {
    await Promise.resolve();
  }
}

async function flushTasks(turns = 3): Promise<void> {
  for (let index = 0; index < turns; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function absentRuntimeStatus() {
  return {
    channel: "stable",
    defaultRouteUrl: null,
    proxyPort: null,
    state: "absent" as const,
    webPort: null,
  };
}

function wedgedRuntimeStatus() {
  return {
    channel: "stable",
    defaultRouteUrl: null,
    proxyPort: 9900,
    state: "wedged" as const,
    webPort: 9901,
  };
}

describe("desktop direct relaunch reclaim", () => {
  beforeEach(() => {
    appOn.mockClear();
    appQuit.mockClear();
    appWhenReady.mockClear();
    appWhenReady.mockImplementation(() => new Promise(() => undefined));
    browserWindowConstructor.mockClear();
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
    waitForBackendHealth.mockClear();
    launchBackendProcess.mockClear();
    stopBackendProcess.mockClear();
    watchBackendExitBeforeReady.mockClear();
  });

  it("reclaims a non-live runtime before spawning the backend", async () => {
    const events: string[] = [];
    const readRuntimeStatus = vi
      .fn()
      .mockReturnValueOnce(wedgedRuntimeStatus())
      .mockReturnValueOnce(absentRuntimeStatus());
    const reclaimRuntime = vi.fn(() => {
      events.push("reclaim");
    });
    launchBackendProcess.mockImplementationOnce(() => {
      events.push("launch");
      return {
        child: backendChild,
        launch: {
          args: [],
          command: "transport-matters",
          cwd: "/tmp/workspace",
          env: {},
        },
      };
    });

    const { registerAppLifecycle } = await import("./main.js");

    appWhenReady.mockResolvedValue(undefined);
    registerAppLifecycle({
      env: { TRANSPORT_MATTERS_CHANNEL: "stable" },
      readRuntimeStatus,
      reclaimRuntime,
    });
    await flushPromiseQueue();
    await flushTasks();

    expect(events).toEqual(["reclaim", "launch"]);
    expect(reclaimRuntime).toHaveBeenCalledWith(
      expect.objectContaining({ id: "stable" }),
      { TRANSPORT_MATTERS_CHANNEL: "stable" },
      process.cwd(),
    );
    expect(launchBackendProcess).toHaveBeenCalledOnce();
  });
});
