import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_CANVAS_GESTURE_MODIFIER, migrateKeymapState, useKeymapStore } from "./keymapStore";
import { FRONTEND_STORAGE_KEYS } from "./persistence";

function persistCanvasGestureModifier(value: unknown, version = 1): void {
  localStorage.setItem(
    FRONTEND_STORAGE_KEYS.keymapStore,
    JSON.stringify({
      state: { canvasGestureModifier: value },
      version,
    }),
  );
}

beforeEach(() => {
  useKeymapStore.setState({ canvasGestureModifier: DEFAULT_CANVAS_GESTURE_MODIFIER });
  localStorage.clear();
});

describe("keymapStore", () => {
  it("defaults the canvas gesture modifier to Shift on a fresh profile", () => {
    expect(useKeymapStore.getState().canvasGestureModifier).toBe("Shift");
  });

  it("persists the selected canvas gesture modifier under the keymap storage key", () => {
    useKeymapStore.getState().setCanvasGestureModifier("Space");

    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.keymapStore);
    expect(raw).not.toBeNull();
    const persisted = JSON.parse(raw ?? "{}") as {
      state?: { canvasGestureModifier?: string };
    };
    expect(persisted.state?.canvasGestureModifier).toBe("Space");
  });

  it("rehydrates Space after a reload", async () => {
    useKeymapStore.setState({ canvasGestureModifier: "Shift" });
    persistCanvasGestureModifier("Space");

    await useKeymapStore.persist.rehydrate();

    expect(useKeymapStore.getState().canvasGestureModifier).toBe("Space");
  });

  it("resets invalid persisted values to Shift on reload", async () => {
    for (const invalid of ["Meta", "Alt", "", null, 42]) {
      useKeymapStore.setState({ canvasGestureModifier: "Space" });
      persistCanvasGestureModifier(invalid);

      await useKeymapStore.persist.rehydrate();

      expect(useKeymapStore.getState().canvasGestureModifier).toBe("Shift");
    }
  });

  describe("migrateKeymapState", () => {
    it("keeps Shift and Space and resets unknown values", () => {
      expect(migrateKeymapState({ canvasGestureModifier: "Shift" })).toEqual({
        canvasGestureModifier: "Shift",
      });
      expect(migrateKeymapState({ canvasGestureModifier: "Space" })).toEqual({
        canvasGestureModifier: "Space",
      });
      expect(migrateKeymapState({ canvasGestureModifier: "Legacy" })).toEqual({
        canvasGestureModifier: "Shift",
      });
    });

    it("resets malformed payloads to Shift", () => {
      for (const malformed of [undefined, null, "corrupted", 42, ["Space"]]) {
        expect(migrateKeymapState(malformed)).toEqual({ canvasGestureModifier: "Shift" });
      }
    });
  });
});
