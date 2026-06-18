import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  type CanvasGestureModifier,
  DEFAULT_CANVAS_GESTURE_MODIFIER,
  isCanvasGestureModifier,
} from "../keybindings/gestureModifier";
import { isRecord } from "../theme/types";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "./persistence";

export {
  CANVAS_GESTURE_MODIFIERS,
  type CanvasGestureModifier,
  DEFAULT_CANVAS_GESTURE_MODIFIER,
  isCanvasGestureModifier,
} from "../keybindings/gestureModifier";

export interface PersistedKeymapSlice {
  canvasGestureModifier: CanvasGestureModifier;
}

export interface KeymapState extends PersistedKeymapSlice {
  setCanvasGestureModifier: (modifier: CanvasGestureModifier) => void;
}

const KEYMAP_STORE_VERSION = 1;

function defaultPersistedSlice(): PersistedKeymapSlice {
  return { canvasGestureModifier: DEFAULT_CANVAS_GESTURE_MODIFIER };
}

export const migrateKeymapState = (persisted: unknown): PersistedKeymapSlice => {
  if (!isRecord(persisted)) return defaultPersistedSlice();
  return {
    canvasGestureModifier: isCanvasGestureModifier(persisted.canvasGestureModifier)
      ? persisted.canvasGestureModifier
      : DEFAULT_CANVAS_GESTURE_MODIFIER,
  };
};

export const useKeymapStore = create<KeymapState>()(
  persist(
    (set) => ({
      canvasGestureModifier: DEFAULT_CANVAS_GESTURE_MODIFIER,
      setCanvasGestureModifier: (modifier) => set({ canvasGestureModifier: modifier }),
    }),
    {
      name: FRONTEND_STORAGE_KEYS.keymapStore,
      storage: createFrontendPersistStorage(),
      // `migrate` handles older versions; `merge` validates every load, including
      // corrupted current-version payloads, so unknown values reset to Shift.
      version: KEYMAP_STORE_VERSION,
      migrate: migrateKeymapState,
      merge: (persisted, current) => ({ ...current, ...migrateKeymapState(persisted) }),
      partialize: (state) => ({ canvasGestureModifier: state.canvasGestureModifier }),
    },
  ),
);
