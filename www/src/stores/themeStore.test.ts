import { beforeEach, describe, expect, it } from "vitest";
import { presetThemes } from "../theme/presets";
import { FRONTEND_STORAGE_KEYS } from "./persistence";
import { migrateThemeState, useThemeStore } from "./themeStore";

const littleorgans = presetThemes[0];
if (!littleorgans) throw new Error("expected bundled presets");

const openWater = presetThemes.find((theme) => theme.id === "open-water");
if (!openWater) throw new Error("expected open-water preset");

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

  it("cycleTheme walks every bundled preset and wraps without returning to unthemed", () => {
    const first = presetThemes[0];
    const last = presetThemes.at(-1);
    if (!first || !last) throw new Error("expected bundled presets");

    for (const preset of presetThemes) {
      useThemeStore.getState().cycleTheme();
      expect(useThemeStore.getState().theme?.id).toBe(preset.id);
    }

    useThemeStore.getState().cycleTheme();
    expect(useThemeStore.getState().theme?.id).toBe(first.id);

    useThemeStore.getState().setTheme(last);
    useThemeStore.getState().cycleTheme();
    expect(useThemeStore.getState().theme?.id).toBe(first.id);
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

  describe("migrateThemeState", () => {
    it("resets to the default theme when the persisted payload is absent", () => {
      expect(() => migrateThemeState(undefined)).not.toThrow();
      const migrated = migrateThemeState(undefined);
      expect(migrated.theme?.id).toBe("open-water");
      expect(migrated.liveDayCycle).toBe(true);
    });

    it("resets to the default theme when the versioned payload is malformed", () => {
      for (const malformed of [null, "corrupted", 42, [openWater]]) {
        expect(() => migrateThemeState(malformed)).not.toThrow();
        expect(migrateThemeState(malformed).theme?.id).toBe("open-water");
        expect(migrateThemeState(malformed).liveDayCycle).toBe(true);
      }
    });

    it("resets the theme when a record payload has no usable theme", () => {
      for (const malformed of [{}, { theme: undefined }, { theme: "open-water" }]) {
        const migrated = migrateThemeState(malformed);
        expect(migrated.theme?.id).toBe("open-water");
        expect(migrated.theme).not.toBeUndefined();
        expect(migrated.liveDayCycle).toBe(true);
      }
    });

    it("preserves an explicit unthemed (theme: null) choice and its liveDayCycle", () => {
      const migrated = migrateThemeState({ theme: null, liveDayCycle: false });
      expect(migrated.theme).toBeNull();
      expect(migrated.liveDayCycle).toBe(false);
    });

    it("rehydrates a legacy reference-sea-ii theme onto reference-sea", () => {
      const legacyPayload = {
        theme: { ...openWater, settings: { ...openWater.settings, sceneId: "reference-sea-ii" } },
        liveDayCycle: true,
      };
      const migrated = migrateThemeState(legacyPayload);
      expect(migrated.theme?.settings.sceneId).toBe("reference-sea");
      expect(migrated.liveDayCycle).toBe(true);
    });
  });
});
