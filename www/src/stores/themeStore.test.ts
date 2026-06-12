import { beforeEach, describe, expect, it } from "vitest";
import { presetThemes } from "../theme/presets";
import { FRONTEND_STORAGE_KEYS } from "./persistence";
import { useThemeStore } from "./themeStore";

const littleorgans = presetThemes[0];
if (!littleorgans) throw new Error("expected bundled presets");

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: null, liveDayCycle: true });
});

describe("themeStore", () => {
  it("boots with open-water as the out-of-the-box theme", () => {
    expect(useThemeStore.getInitialState().theme?.id).toBe("open-water");
    expect(useThemeStore.getInitialState().liveDayCycle).toBe(true);
  });

  it("setTheme stores the active theme", () => {
    useThemeStore.getState().setTheme(littleorgans);
    expect(useThemeStore.getState().theme?.id).toBe("littleorgans");
  });

  it("clearTheme returns to the unthemed default", () => {
    useThemeStore.getState().setTheme(littleorgans);
    useThemeStore.getState().clearTheme();
    expect(useThemeStore.getState().theme).toBeNull();
  });

  it("setSceneParam writes through to the persisted theme settings", () => {
    useThemeStore.getState().setTheme(littleorgans);
    useThemeStore.getState().setSceneParam("dayProgress", 0.8);

    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBe(0.8);
    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.themeStore);
    expect(raw).toContain('"dayProgress":0.8');
  });

  it("setSceneParam is a no-op while unthemed", () => {
    useThemeStore.getState().setSceneParam("dayProgress", 0.8);
    expect(useThemeStore.getState().theme).toBeNull();
  });

  it("liveDayCycle defaults on and persists as a runtime preference", () => {
    expect(useThemeStore.getState().liveDayCycle).toBe(true);
    useThemeStore.getState().setLiveDayCycle(false);
    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.themeStore);
    expect(raw).toContain('"liveDayCycle":false');
  });

  it("persists the full definition under the theme storage key", () => {
    useThemeStore.getState().setTheme(littleorgans);
    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.themeStore);
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw ?? "{}") as { state: { theme: { id: string } | null } };
    expect(persisted.state.theme?.id).toBe("littleorgans");
  });
});
