import { describe, expect, it, vi } from "vitest";

const exposeInMainWorld = vi.fn();

vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld },
}));

describe("desktop preload", () => {
  it("exposes only the minimal desktop API", async () => {
    const { createDesktopApi } = await import("./preload.js");

    const api = createDesktopApi();

    expect(api).toEqual({ appName: "Transport Matters" });
    expect(Object.isFrozen(api)).toBe(true);
    expect(Object.keys(api)).toEqual(["appName"]);
    expect(exposeInMainWorld).toHaveBeenCalledWith(
      "transportMattersDesktop",
      api,
    );
  });
});
