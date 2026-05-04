import { app, BrowserWindow } from "electron";
import type { BrowserWindowConstructorOptions } from "electron";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const moduleDir = dirname(fileURLToPath(import.meta.url));

export const APP_NAME = "Transport Matters";
export const DEFAULT_RENDERER_URL = "http://127.0.0.1:8788";

export interface MainWindowOptions {
  preloadPath?: string;
  rendererUrl?: string;
}

export function resolvePreloadPath(): string {
  return join(moduleDir, "preload.js");
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

export function registerAppLifecycle(): void {
  void app.whenReady().then(() => {
    createMainWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
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
