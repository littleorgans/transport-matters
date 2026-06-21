import { beforeEach, describe, expect, it } from "vitest";
import {
  canvasCacheKey,
  createCanvasCacheStorage,
  importLegacyCanvasCache,
  LEGACY_CANVAS_CACHE_KEY,
} from "./canvasCacheStorage";

beforeEach(() => {
  localStorage.clear();
});

describe("canvasCacheKey", () => {
  it("namespaces the base canvas key by canvasId", () => {
    expect(canvasCacheKey("space:s1")).toBe("transport-matters-canvas:space:s1");
  });
});

describe("importLegacyCanvasCache", () => {
  it("copies the legacy blob into the per-canvas key once, then clears the legacy key", () => {
    localStorage.setItem(LEGACY_CANVAS_CACHE_KEY, '{"version":1}');

    expect(importLegacyCanvasCache("space:s1", localStorage)).toBe("imported");
    expect(localStorage.getItem(canvasCacheKey("space:s1"))).toBe('{"version":1}');
    expect(localStorage.getItem(LEGACY_CANVAS_CACHE_KEY)).toBeNull();

    // Idempotent: a second call (legacy now gone) is a no-op.
    expect(importLegacyCanvasCache("space:s2", localStorage)).toBe("skipped");
    expect(localStorage.getItem(canvasCacheKey("space:s2"))).toBeNull();
  });

  it("never overwrites an existing per-canvas blob", () => {
    localStorage.setItem(LEGACY_CANVAS_CACHE_KEY, '{"version":1,"from":"legacy"}');
    localStorage.setItem(canvasCacheKey("space:s1"), '{"version":1,"from":"existing"}');

    expect(importLegacyCanvasCache("space:s1", localStorage)).toBe("skipped");
    expect(localStorage.getItem(canvasCacheKey("space:s1"))).toBe(
      '{"version":1,"from":"existing"}',
    );
  });
});

describe("createCanvasCacheStorage", () => {
  it("routes get/set/remove through the active canvasId namespace", () => {
    let active = "space:s1";
    const storage = createCanvasCacheStorage<{ value: number }>(() => active);
    if (!storage) throw new Error("expected storage");

    storage.setItem("ignored-name", { state: { value: 1 }, version: 1 });
    expect(localStorage.getItem(canvasCacheKey("space:s1"))).not.toBeNull();

    active = "space:s2";
    expect(storage.getItem("ignored-name")).toBeNull();

    active = "space:s1";
    expect(storage.getItem("ignored-name")).toEqual({ state: { value: 1 }, version: 1 });

    storage.removeItem("ignored-name");
    expect(localStorage.getItem(canvasCacheKey("space:s1"))).toBeNull();
  });
});
