import { BrowserWindow, dialog, shell } from "electron";
import type { BrowserWindowConstructorOptions } from "electron";

export const APP_NAME = "Transport Matters";
export const DEFAULT_WEB_PORT = 8788;
export const DEFAULT_RENDERER_URL = rendererUrlForPort(DEFAULT_WEB_PORT);

export interface HostedWindowOptions {
  preloadPath: string;
  rendererUrl?: string;
}

export function rendererUrlForPort(webPort: number): string {
  return new URL("/", `http://127.0.0.1:${webPort}`).toString();
}

export function createWindowOptions(
  preloadPath: string,
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

export function createHostedWindow(
  options: HostedWindowOptions,
): BrowserWindow {
  const rendererUrl = normalizeLoopbackHostedUrl(
    options.rendererUrl ?? DEFAULT_RENDERER_URL,
  );

  const window = new BrowserWindow(createWindowOptions(options.preloadPath));

  registerHostedWindowPolicy(window, rendererUrl);
  window.once("ready-to-show", () => {
    window.show();
  });
  void window.loadURL(rendererUrl);

  return window;
}

export function allowsHostedNavigation(
  targetUrl: string,
  rendererUrl: string,
): boolean {
  return parseUrl(targetUrl)?.origin === parseUrl(rendererUrl)?.origin;
}

export function shouldOpenExternal(targetUrl: string): boolean {
  const url = parseUrl(targetUrl);
  return url?.protocol === "https:";
}

export function showHostedLoadFailure(
  failedUrl: string,
  errorDescription: string,
): void {
  dialog.showErrorBox(
    "Transport Matters failed to load",
    `The hosted web app failed to load at ${failedUrl}: ${errorDescription}.`,
  );
}

function registerHostedWindowPolicy(
  window: BrowserWindow,
  rendererUrl: string,
): void {
  window.webContents.on("will-navigate", (event, targetUrl) => {
    if (!allowsHostedNavigation(targetUrl, rendererUrl)) {
      event.preventDefault();
    }
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (shouldOpenExternal(url)) {
      void shell.openExternal(url);
    }
    return { action: "deny" };
  });

  window.webContents.on(
    "did-fail-load",
    (_event, _errorCode, errorDescription, failedUrl, isMainFrame) => {
      if (isMainFrame) {
        showHostedLoadFailure(failedUrl, errorDescription);
      }
    },
  );
}

function normalizeLoopbackHostedUrl(rendererUrl: string): string {
  const url = parseUrl(rendererUrl);
  if (
    url === null ||
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    url.pathname !== "/"
  ) {
    throw new Error(`Invalid Transport Matters hosted web URL: ${rendererUrl}`);
  }
  return url.toString();
}

function parseUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}
