import { describe, expect, it } from "vitest";
import { formatBinding } from "./format";
import { resolveKeybindingPlatform } from "./platform";

const mac = resolveKeybindingPlatform({ window: bridge("darwin") });
const linux = resolveKeybindingPlatform({ window: bridge("linux") });
const windows = resolveKeybindingPlatform({ window: bridge("win32") });

function bridge(platform: string): Window {
  return {
    transportMattersDesktop: {
      appName: "Transport Matters",
      platform,
    },
  } as Window;
}

describe("formatBinding", () => {
  it("formats macOS single modifier chords with Apple symbols", () => {
    expect(formatBinding(["$mod", "k"], mac)).toBe("⌘K");
  });

  it("formats macOS multi modifier chords in Apple order", () => {
    expect(formatBinding(["Shift", "$mod", "Control", "Alt", "k"], mac)).toBe("⌃⌥⇧⌘K");
  });

  it("formats Linux chords with word labels", () => {
    expect(formatBinding(["$mod", "Alt", "Shift", "k"], linux)).toBe("Ctrl+Alt+Shift+K");
  });

  it("formats Windows chords with word labels", () => {
    expect(formatBinding(["Shift", "$mod", "Enter"], windows)).toBe("Ctrl+Shift+Enter");
  });

  it("keeps arbitrary non modifier tokens in input order", () => {
    expect(formatBinding(["$mod", "K", "then", "P"], linux)).toBe("Ctrl+K+then+P");
  });
});
