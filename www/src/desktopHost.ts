// Detects whether the www bundle is running inside the Transport Matters Electron
// shell (where the preload exposes `window.transportMattersDesktop`) versus a plain
// browser. Used to switch on desktop-only chrome such as the title-bar drag region,
// which is meaningless and would swallow clicks in a browser. Keep the bridge key in
// sync with DESKTOP_PRELOAD_BRIDGE_KEY (desktop/src/main.ts) and the preload
// (desktop/src/preload.cts).
export const DESKTOP_BRIDGE_KEY = "transportMattersDesktop";

export type DesktopBridgePlatform =
  | "aix"
  | "android"
  | "darwin"
  | "freebsd"
  | "haiku"
  | "linux"
  | "openbsd"
  | "sunos"
  | "win32"
  | "cygwin"
  | "netbsd"
  | (string & {});

export interface TransportMattersDesktopBridge {
  appName: string;
  platform: DesktopBridgePlatform;
  /** Resolves a dropped File to its OS path; the browser build has no bridge. */
  getPathForFile?: (file: File) => string;
}

declare global {
  interface Window {
    [DESKTOP_BRIDGE_KEY]?: TransportMattersDesktopBridge;
  }
}

export function isDesktopHost(win: Window | undefined = globalWindow()): boolean {
  return win !== undefined && DESKTOP_BRIDGE_KEY in win;
}

function globalWindow(): Window | undefined {
  return typeof window === "undefined" ? undefined : window;
}
