import { describe, expect, it } from "vitest";
import { isDesktopHost } from "./desktopHost";

function fakeWindow(bridge: boolean): Window {
  return (bridge ? { transportMattersDesktop: { appName: "Transport Matters" } } : {}) as Window;
}

describe("desktop host detection", () => {
  it("detects the Electron preload bridge", () => {
    expect(isDesktopHost(fakeWindow(true))).toBe(true);
  });

  it("reports a plain browser as not a desktop host", () => {
    expect(isDesktopHost(fakeWindow(false))).toBe(false);
  });
});
