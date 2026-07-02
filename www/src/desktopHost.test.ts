import { describe, expect, it } from "vitest";
import {
  canResolveDroppedFiles,
  getDesktopBridge,
  getDroppedFilePathResolver,
  getPathForDroppedFile,
  isDesktopHost,
} from "./desktopHost";

function fakeWindow(bridge: boolean): Window {
  return (
    bridge ? { transportMattersDesktop: { appName: "Transport Matters", platform: "darwin" } } : {}
  ) as Window;
}

describe("desktop host detection", () => {
  it("detects the Electron preload bridge", () => {
    expect(isDesktopHost(fakeWindow(true))).toBe(true);
  });

  it("reports a plain browser as not a desktop host", () => {
    expect(isDesktopHost(fakeWindow(false))).toBe(false);
  });

  it("exposes the desktop bridge without canvas code reading window directly", () => {
    const win = fakeWindow(true);
    expect(getDesktopBridge(win)?.platform).toBe("darwin");
  });

  it("resolves dropped file paths through the desktop bridge only when available", () => {
    const file = new File(["x"], "x.txt");
    const win = {
      transportMattersDesktop: {
        appName: "Transport Matters",
        platform: "darwin",
        getPathForFile: () => "/tmp/x.txt",
      },
    } as unknown as Window;

    expect(canResolveDroppedFiles(win)).toBe(true);
    expect(getDroppedFilePathResolver(win)?.(file)).toBe("/tmp/x.txt");
    expect(getPathForDroppedFile(file, win)).toBe("/tmp/x.txt");
    expect(canResolveDroppedFiles(fakeWindow(true))).toBe(false);
    expect(getPathForDroppedFile(file, fakeWindow(false))).toBeNull();
  });
});
