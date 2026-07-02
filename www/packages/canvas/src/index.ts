/**
 * @tm/canvas — the Ark/BEM desktop product: session canvas, pane engine,
 * ambient scenes, and the theme system (canvas-only by locked decision).
 * The shell lazy-loads the two routes; the theme store and token control
 * are public so the shell's composition test can pin the theme clean
 * break. The localStorage registry lives on the css-free `./storageKeys`
 * subpath so Node-side test transforms (Playwright) never pull the
 * component graph.
 */
export { clearThemeTokens } from "./hooks/useThemeTokens";
export { CanvasLabRoute } from "./session-canvas/lab/CanvasLabRoute";
export { SessionCanvasRoute } from "./session-canvas/SessionCanvasRoute";
export { useThemeStore } from "./stores/themeStore";
