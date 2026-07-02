import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../stores/themeStore";
import { presetTheme } from "../theme/presets";
import { bootstrapThemeTokens, clearThemeTokens, useThemeTokens } from "./useThemeTokens";

const rootStyle = () => document.documentElement.style;

const openWater = presetTheme("open-water");
const littleorgans = presetTheme("littleorgans");
if (!openWater || !littleorgans) throw new Error("expected bundled presets");

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

afterEach(() => {
  clearThemeTokens();
});

describe("useThemeTokens", () => {
  it("can bootstrap tokens synchronously before a canvas route paints", () => {
    useThemeStore.setState({ theme: openWater });

    bootstrapThemeTokens();

    expect(rootStyle().getPropertyValue("--color-accent")).not.toBe("");
    expect(rootStyle().getPropertyValue("--pane-blur")).toBe("blur(18px) saturate(120%)");
  });

  it("writes all seven tokens when a theme is active", () => {
    useThemeStore.setState({ theme: openWater });
    renderHook(() => useThemeTokens());

    expect(rootStyle().getPropertyValue("--color-accent")).not.toBe("");
    expect(rootStyle().getPropertyValue("--accent-rgb")).toMatch(/^\d+ \d+ \d+$/);
    expect(rootStyle().getPropertyValue("--pane-radius")).toMatch(/px$/);
    expect(rootStyle().getPropertyValue("--pane-surface-alpha")).toBe("0.5");
    expect(rootStyle().getPropertyValue("--pane-border-color")).not.toBe("");
    expect(rootStyle().getPropertyValue("--pane-blur")).toBe("blur(18px) saturate(120%)");
    expect(rootStyle().getPropertyValue("--pane-shadow")).not.toBe("");
  });

  it("maps glass off to a none blur", () => {
    useThemeStore.setState({ theme: littleorgans });
    renderHook(() => useThemeTokens());
    expect(rootStyle().getPropertyValue("--pane-blur")).toBe("none");
  });

  it("removes the inline tokens when the theme clears", () => {
    useThemeStore.setState({ theme: openWater });
    renderHook(() => useThemeTokens());
    act(() => {
      useThemeStore.setState({ theme: null });
    });

    expect(rootStyle().getPropertyValue("--pane-blur")).toBe("");
    expect(rootStyle().getPropertyValue("--color-accent")).toBe("");
  });
});
