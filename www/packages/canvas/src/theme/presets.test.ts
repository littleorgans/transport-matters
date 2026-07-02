import { describe, expect, it } from "vitest";
import { themeValidationDeps } from "./deps";
import { parseThemeJson, serializeTheme } from "./import-export";
import { presetTheme, presetThemes } from "./presets";

describe("theme presets", () => {
  it("bundles every preset as a valid ThemeDefinition", () => {
    expect(presetThemes.map((theme) => theme.id)).toEqual(["littleorgans", "open-water"]);
  });

  it("round-trips each preset through the canonical export format", () => {
    for (const theme of presetThemes) {
      const result = parseThemeJson(serializeTheme(theme), themeValidationDeps);
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.theme).toEqual(theme);
    }
  });

  it("resolves presets by id", () => {
    expect(presetTheme("open-water")?.name).toBe("Open water");
    expect(presetTheme("missing")).toBeUndefined();
  });

  it("rejects a theme that drifts from the scene registry", () => {
    const base = presetTheme("littleorgans");
    if (!base) throw new Error("expected bundled preset");
    const drifted = { ...base, settings: { ...base.settings, sceneId: "retired-scene" } };
    const result = parseThemeJson(JSON.stringify(drifted), themeValidationDeps);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.cause).toBe("unknown scene: retired-scene");
  });
});
