import { afterEach, describe, expect, it } from "vitest";
import {
  getKeybindingPlatform,
  precompileModTokens,
  resetKeybindingPlatformCache,
  resolveKeybindingPlatform,
  resolveModToken,
} from "./platform";

function fakeWindow(platform: string): Window {
  return {
    transportMattersDesktop: {
      appName: "Transport Matters",
      platform,
    },
  } as Window;
}

function fakeNavigator(platform: string): Navigator {
  return {
    userAgent: "Mozilla/5.0",
    userAgentData: { platform },
  } as unknown as Navigator;
}

describe("keybinding platform", () => {
  afterEach(() => {
    resetKeybindingPlatformCache();
    delete window.transportMattersDesktop;
  });

  it("uses the desktop bridge platform before navigator fallback", () => {
    const platform = resolveKeybindingPlatform({
      navigator: fakeNavigator("macOS"),
      window: fakeWindow("linux"),
    });

    expect(platform).toEqual({
      isMac: false,
      modToken: "Control",
      rawPlatform: "linux",
      source: "desktop-bridge",
    });
  });

  it("falls back to navigator userAgentData when the bridge is absent", () => {
    const platform = resolveKeybindingPlatform({
      navigator: fakeNavigator("macOS"),
      window: {} as Window,
    });

    expect(platform).toEqual({
      isMac: true,
      modToken: "Meta",
      rawPlatform: "macOS",
      source: "navigator",
    });
  });

  it("falls back to navigator userAgent when userAgentData is absent", () => {
    const platform = resolveKeybindingPlatform({
      navigator: { userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" } as Navigator,
      window: {} as Window,
    });

    expect(platform.modToken).toBe("Meta");
    expect(platform.source).toBe("navigator");
  });

  it("precompiles $mod to Meta on macOS and Control elsewhere", () => {
    const mac = resolveKeybindingPlatform({ window: fakeWindow("darwin") });
    const linux = resolveKeybindingPlatform({ window: fakeWindow("linux") });

    expect(resolveModToken(mac)).toBe("Meta");
    expect(precompileModTokens(["$mod", "Shift", "K"], mac)).toEqual(["Meta", "Shift", "K"]);
    expect(resolveModToken(linux)).toBe("Control");
    expect(precompileModTokens(["$mod", "Shift", "K"], linux)).toEqual(["Control", "Shift", "K"]);
  });

  it("memoizes the resolved runtime platform", () => {
    window.transportMattersDesktop = {
      appName: "Transport Matters",
      platform: "darwin",
    };
    expect(getKeybindingPlatform().modToken).toBe("Meta");

    window.transportMattersDesktop = {
      appName: "Transport Matters",
      platform: "linux",
    };
    expect(getKeybindingPlatform().modToken).toBe("Meta");
  });
});
