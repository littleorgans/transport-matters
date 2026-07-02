import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { searchForWorkspaceRoot } from "vite";

const PACKAGE_ROOT = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE_ROOT = searchForWorkspaceRoot(PACKAGE_ROOT);
const DEV_SERVER_URL = "http://127.0.0.1:4173";
const INSPECTOR_PREVIEW_PORT = 4174;
const CANVAS_PREVIEW_PORT = 4175;
const INSPECTOR_PREVIEW_URL = `http://127.0.0.1:${INSPECTOR_PREVIEW_PORT}`;
const CANVAS_PREVIEW_URL = `http://127.0.0.1:${CANVAS_PREVIEW_PORT}`;

function projectRequested(name: string): boolean {
  return process.argv.some(
    (arg, index, args) =>
      arg === `--project=${name}` || (arg === "--project" && args[index + 1] === name),
  );
}

const USE_PREVIEW_SERVER = process.env.PLAYWRIGHT_USE_PREVIEW === "1" || projectRequested("perf");
const DEV_SERVER_COMMAND = USE_PREVIEW_SERVER
  ? "pnpm --filter @tm/shell build && pnpm --filter @tm/shell preview --host 127.0.0.1 --port 4173 --strictPort"
  : "pnpm --filter @tm/shell dev --host 127.0.0.1 --port 4173 --strictPort";

// The bundle matrix runs the REAL production artifacts: each product is
// built and served by `vite preview` at its production base (inspector at
// "/", canvas at "/canvas"). The matrix projects and their preview servers
// register together, gated on one flag: a plain unfiltered run never sees
// the matrix projects, so it cannot execute them against dead ports, and
// the default dev-shell runs stay fast.
//
// Workers re-evaluate this config in fresh processes WITHOUT the runner's
// CLI args, so argv detection alone deregisters the projects there
// ("project not found in the worker process"). Promote the argv signal
// into the environment: workers inherit env, keeping the project list
// identical across runner and workers.
if (projectRequested("matrix-inspector") || projectRequested("matrix-canvas")) {
  process.env.PLAYWRIGHT_MATRIX = "1";
}
const RUN_BUNDLE_MATRIX = process.env.PLAYWRIGHT_MATRIX === "1";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  use: {
    baseURL: DEV_SERVER_URL,
    trace: "on-first-retry",
  },
  // Allow up to 1% of clipped pixels to differ to absorb font anti-aliasing
  // jitter without masking genuine layout regressions.
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
    },
  },
  projects: [
    { name: "chromium", testDir: "./tests/e2e", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", testDir: "./tests/e2e", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", testDir: "./tests/e2e", use: { ...devices["Desktop Safari"] } },
    { name: "visual", testDir: "./tests/visual", use: { ...devices["Desktop Chrome"] } },
    { name: "perf", testDir: "./tests/perf", use: { ...devices["Desktop Chrome"] } },
    ...(RUN_BUNDLE_MATRIX
      ? [
          {
            name: "matrix-inspector",
            testDir: "./tests/matrix/inspector",
            use: { ...devices["Desktop Chrome"], baseURL: INSPECTOR_PREVIEW_URL },
          },
          {
            name: "matrix-canvas",
            testDir: "./tests/matrix/canvas",
            use: { ...devices["Desktop Chrome"], baseURL: CANVAS_PREVIEW_URL },
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: DEV_SERVER_COMMAND,
      cwd: WORKSPACE_ROOT,
      url: DEV_SERVER_URL,
      reuseExistingServer: !process.env.CI && !USE_PREVIEW_SERVER,
    },
    ...(RUN_BUNDLE_MATRIX
      ? [
          {
            command: `pnpm --filter @tm/inspector build && pnpm --filter @tm/inspector preview --host 127.0.0.1 --port ${INSPECTOR_PREVIEW_PORT} --strictPort`,
            cwd: WORKSPACE_ROOT,
            url: INSPECTOR_PREVIEW_URL,
            reuseExistingServer: false,
            timeout: 180_000,
          },
          {
            command: `pnpm --filter @tm/canvas build && pnpm --filter @tm/canvas preview --host 127.0.0.1 --port ${CANVAS_PREVIEW_PORT} --strictPort`,
            cwd: WORKSPACE_ROOT,
            // vite preview serves the canvas bundle under its base.
            url: `${CANVAS_PREVIEW_URL}/canvas/`,
            reuseExistingServer: false,
            timeout: 180_000,
          },
        ]
      : []),
  ],
});
