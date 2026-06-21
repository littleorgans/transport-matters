import { createJSONStorage, type PersistStorage } from "zustand/middleware";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";

/** The bare key the pre-Spaces build persisted its single canvas under. */
export const LEGACY_CANVAS_CACHE_KEY = FRONTEND_STORAGE_KEYS.canvasStore;

/** localStorage key for one canvas's cached layout, namespaced by canvasId. */
export function canvasCacheKey(canvasId: string): string {
  return `${FRONTEND_STORAGE_KEYS.canvasStore}:${canvasId}`;
}

/**
 * One-time migration: the pre-Spaces build kept a single canvas under the bare
 * LEGACY key. Copy it into the per-canvas key the first time a canvas is
 * initialized, so the user's one canvas becomes the default Canvas of the Space
 * they open first. Idempotent — never overwrites an existing per-canvas blob,
 * and clears the legacy key after a successful copy so it imports exactly once.
 */
export function importLegacyCanvasCache(
  canvasId: string,
  storage: Storage,
): "imported" | "skipped" {
  const target = canvasCacheKey(canvasId);
  if (storage.getItem(target) !== null) return "skipped";
  const legacy = storage.getItem(LEGACY_CANVAS_CACHE_KEY);
  if (legacy === null) return "skipped";
  storage.setItem(target, legacy);
  storage.removeItem(LEGACY_CANVAS_CACHE_KEY);
  return "imported";
}

/**
 * A zustand persist storage that namespaces every read/write by the active
 * canvasId. The `name` zustand passes is ignored; the live canvasId (from
 * `getCanvasId`) keys the cache instead, so switching canvases switches caches.
 */
export function createCanvasCacheStorage<S>(
  getCanvasId: () => string,
): PersistStorage<S> | undefined {
  const inner = createJSONStorage<S>(() => globalThis.localStorage);
  if (!inner) return undefined;
  return {
    getItem: (_name) => inner.getItem(canvasCacheKey(getCanvasId())),
    setItem: (_name, value) => inner.setItem(canvasCacheKey(getCanvasId()), value),
    removeItem: (_name) => inner.removeItem(canvasCacheKey(getCanvasId())),
  };
}
