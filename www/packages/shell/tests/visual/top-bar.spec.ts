import { expect, test } from "@playwright/test";
import { setupVisualTest } from "./fixtures";

// Top bar states worth locking in. Paused is covered by paused-header.spec.ts.
test.describe("app top bar — arm states", () => {
  test("armed (no paused flow)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, { armed: true, paused: false });
    await page.goto("/");
    await page.getByRole("heading", { name: "Transport Matters" }).waitFor();

    await expect(page).toHaveScreenshot("topbar-armed.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 72 },
    });
  });

  test("disarmed", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, { armed: false, paused: false });
    await page.goto("/");
    await page.getByRole("heading", { name: "Transport Matters" }).waitFor();

    await expect(page).toHaveScreenshot("topbar-disarmed.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 72 },
    });
  });
});
