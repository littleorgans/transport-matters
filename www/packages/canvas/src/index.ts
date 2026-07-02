/**
 * @tm/canvas — the Ark/BEM desktop product: session canvas, pane engine,
 * ambient scenes, and the theme system (canvas-only by locked decision).
 * The shell lazy-loads the two routes; the theme store and token control
 * are public so the shell's composition test can pin the theme clean
 * break; `CANVAS_STORAGE_KEYS` is public so the shell can assert the two
 * products' localStorage registries never collide.
 */
export { clearThemeTokens } from "./hooks/useThemeTokens";
export { CanvasLabRoute } from "./session-canvas/lab/CanvasLabRoute";
export { CANVAS_STORAGE_KEYS } from "./session-canvas/persistence/storageKeys";
export { SessionCanvasRoute } from "./session-canvas/SessionCanvasRoute";
export { useThemeStore } from "./stores/themeStore";
