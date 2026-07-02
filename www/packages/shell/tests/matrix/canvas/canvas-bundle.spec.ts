import { expect, test } from "@playwright/test";

test.use({ reducedMotion: "reduce" });

// The REAL built canvas bundle served by `vite preview` at its production
// base "/canvas". The entry runs mountWindowChrome() and
// bootstrapThemeTokens() before render, so a green boot proves the
// per-entry wiring; the asset checks prove every URL respects the base.
test("the built canvas bundle boots at /canvas with assets under the base", async ({ page }) => {
  const missingAssets: string[] = [];
  const servedAssets: string[] = [];
  page.on("response", (response) => {
    const { pathname } = new URL(response.url());
    if (!pathname.startsWith("/canvas/assets/")) return;
    (response.ok() ? servedAssets : missingAssets).push(pathname);
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");

  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  expect(missingAssets).toEqual([]);
  expect(servedAssets.length).toBeGreaterThan(0);
});

// Desktop smoke: the desktop shell loads this same bundle at /canvas
// (rendererUrlForPort's default; desktop is verification, not
// modification). With the desktop bridge present, the host chrome mounts
// the window drag strip that only renders inside the Electron shell.
test("desktop smoke: canvas boots under the desktop bridge with window chrome", async ({
  page,
}) => {
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).transportMattersDesktop = {};
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");

  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  await expect(page.locator(".window-drag-region")).toHaveCount(1);
});
