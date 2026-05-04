import { beforeEach, describe, expect, it, vi } from "vitest";

const browserWindowConstructor = vi.fn();
const loadURL = vi.fn();
const once = vi.fn();
const show = vi.fn();

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
    return { loadURL, once, show };
  }),
}));

describe("desktop main process", () => {
  beforeEach(() => {
    browserWindowConstructor.mockClear();
    loadURL.mockClear();
    once.mockClear();
    show.mockClear();
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
    expect(loadURL).toHaveBeenCalledWith("http://127.0.0.1:8788");
  });
});
