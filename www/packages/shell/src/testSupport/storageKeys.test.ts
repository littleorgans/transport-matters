/**
 * Both products are served from one origin (inspector at /, canvas at
 * /canvas), so their localStorage registries share a namespace. This shell
 * test replaces the uniqueness the old single FRONTEND_STORAGE_KEYS
 * registry guaranteed by construction.
 */
import { CANVAS_STORAGE_KEYS } from "@tm/canvas/storageKeys";
import { INSPECTOR_STORAGE_KEYS } from "@tm/inspector/storageKeys";
import { describe, expect, it } from "vitest";

describe("cross-product storage keys", () => {
  it("never collide between inspector and canvas", () => {
    const inspector = Object.values(INSPECTOR_STORAGE_KEYS);
    const canvas = Object.values(CANVAS_STORAGE_KEYS);
    const all = [...inspector, ...canvas];
    expect(new Set(all).size).toBe(all.length);
  });

  it("all live under the transport-matters namespace", () => {
    for (const key of [
      ...Object.values(INSPECTOR_STORAGE_KEYS),
      ...Object.values(CANVAS_STORAGE_KEYS),
    ]) {
      expect(key).toMatch(/^transport-matters[-.]/);
    }
  });
});
