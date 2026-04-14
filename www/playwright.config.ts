import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  // ── Visual regression tolerance ──
  // Allow up to 1% of clipped pixels to differ to absorb font anti-aliasing
  // jitter without masking genuine layout regressions.
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
    },
  },
  projects: [
    // ── Behavioral e2e — three browsers ──
    { name: "chromium", testDir: "./tests/e2e", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", testDir: "./tests/e2e", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", testDir: "./tests/e2e", use: { ...devices["Desktop Safari"] } },

    // ── Visual regression — chromium only to keep snapshots reproducible ──
    { name: "visual", testDir: "./tests/visual", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
  },
});
