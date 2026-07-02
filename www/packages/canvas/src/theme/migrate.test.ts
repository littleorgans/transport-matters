import { describe, expect, it } from "vitest";
import { normalizeLegacyTheme } from "./migrate";

describe("normalizeLegacyTheme", () => {
  it("rewrites the collapsed reference-sea-ii sceneId, preserving other fields", () => {
    const legacy = {
      schema: 1,
      id: "open-water",
      settings: { sceneId: "reference-sea-ii", veil: 0.5, sceneParams: {} },
    };

    const result = normalizeLegacyTheme(legacy) as typeof legacy;

    expect(result.settings.sceneId).toBe("reference-sea");
    expect(result.settings.veil).toBe(0.5);
    expect(result.id).toBe("open-water");
    // Pure rewrite: the input is not mutated.
    expect(legacy.settings.sceneId).toBe("reference-sea-ii");
  });

  it("returns the same reference for a current sceneId (callers detect no-op via ===)", () => {
    const current = { schema: 1, settings: { sceneId: "reference-sea", sceneParams: {} } };
    expect(normalizeLegacyTheme(current)).toBe(current);
  });

  it("is identity for non-theme inputs", () => {
    expect(normalizeLegacyTheme(null)).toBeNull();
    expect(normalizeLegacyTheme("nope")).toBe("nope");
    expect(normalizeLegacyTheme({ schema: 1 })).toEqual({ schema: 1 });
    const noScene = { settings: { veil: 0.5 } };
    expect(normalizeLegacyTheme(noScene)).toBe(noScene);
  });
});
