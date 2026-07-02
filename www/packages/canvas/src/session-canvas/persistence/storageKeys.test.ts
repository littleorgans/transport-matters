import { describe, expect, it } from "vitest";
import { CANVAS_STORAGE_KEYS } from "./storageKeys";

describe("canvas storage keys", () => {
  it("keeps the canvas storage keys stable", () => {
    expect(CANVAS_STORAGE_KEYS.themeStore).toBe("transport-matters-theme");
    expect(CANVAS_STORAGE_KEYS.capturedRunStore).toBe("transport-matters-captured-run");
    expect(CANVAS_STORAGE_KEYS.canvasStore).toBe("transport-matters-canvas");
    expect(CANVAS_STORAGE_KEYS.canvasLabStore).toBe("transport-matters-canvas-lab");
    expect(CANVAS_STORAGE_KEYS.keymapStore).toBe("transport-matters-keymap");
  });
});
