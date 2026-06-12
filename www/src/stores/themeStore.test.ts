import { beforeEach, describe, expect, it } from "vitest";
import { presetThemes } from "../theme/presets";
import { FRONTEND_STORAGE_KEYS } from "./persistence";
import { useThemeStore } from "./themeStore";

const littleorgans = presetThemes[0];
if (!littleorgans) throw new Error("expected bundled presets");

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: null });
});

describe("themeStore", () => {
  it("setTheme stores the active theme", () => {
    useThemeStore.getState().setTheme(littleorgans);
    expect(useThemeStore.getState().theme?.id).toBe("littleorgans");
  });

  it("clearTheme returns to the unthemed default", () => {
    useThemeStore.getState().setTheme(littleorgans);
    useThemeStore.getState().clearTheme();
    expect(useThemeStore.getState().theme).toBeNull();
  });

  it("persists the full definition under the theme storage key", () => {
    useThemeStore.getState().setTheme(littleorgans);
    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.themeStore);
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw ?? "{}") as { state: { theme: { id: string } | null } };
    expect(persisted.state.theme?.id).toBe("littleorgans");
  });
});
