import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { searchForWorkspaceRoot } from "vite";

const PACKAGE_ROOT = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE_ROOT = searchForWorkspaceRoot(PACKAGE_ROOT);
const DEV_SERVER_URL = "http://127.0.0.1:4173";
const USE_PREVIEW_SERVER =
  process.env.PLAYWRIGHT_USE_PREVIEW === "1" ||
  process.argv.some(
    (arg, index, args) =>
      arg === "--project=perf" || (arg === "--project" && args[index + 1] === "perf"),
  );
const DEV_SERVER_COMMAND = USE_PREVIEW_SERVER
  ? "pnpm --filter @tm/shell build && pnpm --filter @tm/shell preview --host 127.0.0.1 --port 4173 --strictPort"
  : "pnpm --filter @tm/shell dev --host 127.0.0.1 --port 4173 --strictPort";

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
  ],
  webServer: {
    command: DEV_SERVER_COMMAND,
    cwd: WORKSPACE_ROOT,
    url: DEV_SERVER_URL,
    reuseExistingServer: !process.env.CI && !USE_PREVIEW_SERVER,
  },
});
