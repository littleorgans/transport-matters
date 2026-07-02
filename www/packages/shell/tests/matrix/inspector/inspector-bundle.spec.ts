import { expect, test } from "@playwright/test";

// The REAL built inspector bundle served by `vite preview` at its
// production base "/". Guards the P6 per-entry risks the dev shell can
// mask: entry CSS wiring, the host chrome mount, and asset URLs
// resolving at the root base.
test("the built inspector bundle boots at / with resolving assets", async ({ page }) => {
  const missingAssets: string[] = [];
  page.on("response", (response) => {
    const { pathname } = new URL(response.url());
    if (response.status() === 404 && pathname.startsWith("/assets/")) {
      missingAssets.push(pathname);
    }
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(missingAssets).toEqual([]);
});
