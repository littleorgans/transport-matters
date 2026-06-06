import { beforeEach, describe, expect, it, vi } from "vitest";

const browserWindowConstructor = vi.fn();
const createBrowserWindowInstance = vi.fn();
const dialogShowErrorBox = vi.fn();
const loadURL = vi.fn();
const once = vi.fn();
const preventDefault = vi.fn();
const setWindowOpenHandler = vi.fn();
const show = vi.fn();
const webContentsOn = vi.fn();

function createBrowserWindowFixture(): void {
  createBrowserWindowInstance.mockImplementation(() => ({
    loadURL,
    once,
    show,
    webContents: {
      on: webContentsOn,
      setWindowOpenHandler,
    },
  }));
}

function handlerForWebContentsEvent(event: string): (...args: unknown[]) => void {
  const call = webContentsOn.mock.calls.find(([eventName]) => eventName === event);
  if (call === undefined) {
    throw new Error(`No webContents handler was registered for ${event}.`);
  }
  return call[1] as (...args: unknown[]) => void;
}

vi.mock("electron", () => ({
  BrowserWindow: vi.fn(function BrowserWindow(
    options: Record<string, unknown>,
  ) {
    browserWindowConstructor(options);
    return createBrowserWindowInstance();
  }),
  dialog: {
    showErrorBox: dialogShowErrorBox,
  },
  shell: {
    openExternal: vi.fn(),
  },
}));

describe("desktop hosted window", () => {
  beforeEach(() => {
    browserWindowConstructor.mockReset();
    createBrowserWindowInstance.mockReset();
    dialogShowErrorBox.mockClear();
    loadURL.mockClear();
    once.mockClear();
    preventDefault.mockClear();
    setWindowOpenHandler.mockClear();
    show.mockClear();
    webContentsOn.mockClear();
    createBrowserWindowFixture();
  });

  it("constructs a loopback hosted web URL with a canvas route", async () => {
    const { rendererUrlForPort } = await import("./window.js");

    expect(rendererUrlForPort(9901)).toBe("http://127.0.0.1:9901/canvas");
    expect(rendererUrlForPort(9901, "/")).toBe("http://127.0.0.1:9901/");
  });

  it("loads the hosted loopback URL in a secure BrowserWindow", async () => {
    const { createHostedWindow } = await import("./window.js");

    createHostedWindow({
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:8788/canvas",
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
    expect(loadURL).toHaveBeenCalledWith("http://127.0.0.1:8788/canvas");
  });

  it("blocks top level navigation away from the health checked origin", async () => {
    const { createHostedWindow } = await import("./window.js");

    createHostedWindow({
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:8788/",
    });

    const willNavigate = handlerForWebContentsEvent("will-navigate");
    willNavigate({ preventDefault }, "http://127.0.0.1:8788/exchanges");
    expect(preventDefault).not.toHaveBeenCalled();

    willNavigate({ preventDefault }, "http://127.0.0.1:8789/");
    expect(preventDefault).toHaveBeenCalledOnce();
  });

  it("blocks new windows and routes safe external URLs to the OS", async () => {
    const { shell } = await import("electron");
    const { createHostedWindow } = await import("./window.js");

    createHostedWindow({
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:8788/",
    });

    const windowOpenHandler = setWindowOpenHandler.mock.calls[0]?.[0];
    expect(windowOpenHandler).toBeDefined();
    expect(windowOpenHandler({ url: "http://127.0.0.1:8788/exchanges" })).toEqual({
      action: "deny",
    });
    expect(windowOpenHandler({ url: "https://example.com/docs" })).toEqual({
      action: "deny",
    });
    expect(shell.openExternal).toHaveBeenCalledWith("https://example.com/docs");
  });

  it("shows a desktop side error when the hosted app fails to load", async () => {
    const { createHostedWindow } = await import("./window.js");

    createHostedWindow({
      preloadPath: "/tmp/transport-matters/preload.js",
      rendererUrl: "http://127.0.0.1:8788/",
    });

    const didFailLoad = handlerForWebContentsEvent("did-fail-load");
    didFailLoad(
      {},
      -102,
      "Connection refused",
      "http://127.0.0.1:8788/",
      true,
    );

    expect(dialogShowErrorBox).toHaveBeenCalledWith(
      "Transport Matters failed to load",
      "The hosted web app failed to load at http://127.0.0.1:8788/: Connection refused.",
    );
  });
});
