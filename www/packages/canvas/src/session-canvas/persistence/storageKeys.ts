/**
 * Canvas-owned localStorage key registry. The inspector keeps its own
 * registry in its `stores/persistence.ts`; both products share one origin,
 * so a shell-level test asserts the two registries never collide.
 */
export const CANVAS_STORAGE_KEYS = {
  themeStore: "transport-matters-theme",
  capturedRunStore: "transport-matters-captured-run",
  canvasStore: "transport-matters-canvas",
  canvasLabStore: "transport-matters-canvas-lab",
  keymapStore: "transport-matters-keymap",
} as const;
