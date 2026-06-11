// CommonJS preload. A sandboxed Electron preload (webPreferences.sandbox:
// true) is evaluated as CommonJS, but this package is `"type": "module"`, so
// the preload is authored as `.cts` (tsc emits `dist/preload.cjs`) using the
// CommonJS `import = require` form to satisfy `verbatimModuleSyntax`. Loading
// an ESM `dist/preload.js` here would throw "Cannot use import statement
// outside a module" at preload time.
import electron = require("electron");

// The exposed key mirrors DESKTOP_PRELOAD_BRIDGE_KEY in main.ts (read back by
// the package smoke) and the value mirrors APP_NAME in window.ts. These live
// across the CommonJS / ESM module boundary, so the literals are duplicated
// intentionally; keep the three in sync.
// getPathForFile is the only sanctioned way to learn a dropped File's OS path
// (reference semantics for canvas file drops; the browser build has no bridge).
const desktopApi = Object.freeze({
  appName: "Transport Matters",
  getPathForFile: (file: File): string => electron.webUtils.getPathForFile(file),
});

electron.contextBridge.exposeInMainWorld("transportMattersDesktop", desktopApi);
