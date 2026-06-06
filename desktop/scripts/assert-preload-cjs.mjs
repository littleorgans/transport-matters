// Post-build guard: the Electron preload must be CommonJS.
//
// This package is `"type": "module"`, so a `.js` preload would be emitted as
// ESM. A sandboxed preload (webPreferences.sandbox: true) is evaluated as
// CommonJS, so an ESM `import` throws "Cannot use import statement outside a
// module" at preload time and the renderer loses its contextBridge. The build
// emits `dist/preload.cjs` from `src/preload.cts`; this asserts that contract
// holds so the regression can never ship green again.
import { existsSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const distDir = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const preloadCjs = join(distDir, "preload.cjs");

// tsc does not delete orphaned outputs when a source is renamed, so a checkout
// that built before `preload.ts` became `preload.cts` carries a stale ESM
// `dist/preload.js` (dist is gitignored, so it survives the rename). It is inert
// (resolvePreloadPath points at preload.cjs) but confusing, and a fresh CI
// checkout never has it. Remove any stale ESM preload artifacts rather than
// failing the build on them; the real contract is checked below.
for (const stray of ["preload.js", "preload.js.map", "preload.d.ts", "preload.d.ts.map"]) {
  const strayPath = join(distDir, stray);
  if (existsSync(strayPath)) {
    rmSync(strayPath);
    console.log(`Preload guard: removed stale pre-rename artifact dist/${stray}.`);
  }
}

const failures = [];

if (!existsSync(preloadCjs)) {
  failures.push(`missing ${preloadCjs} (the build must emit a CommonJS preload)`);
} else if (/^\s*(import|export)\s/m.test(readFileSync(preloadCjs, "utf8"))) {
  failures.push(
    `${preloadCjs} contains a top-level ESM import/export; sandboxed Electron preloads must be CommonJS`,
  );
}

if (failures.length > 0) {
  console.error("Preload CommonJS guard FAILED:");
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  process.exit(1);
}

console.log("Preload CommonJS guard OK: dist/preload.cjs is CommonJS.");
