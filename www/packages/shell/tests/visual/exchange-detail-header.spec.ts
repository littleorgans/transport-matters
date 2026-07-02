import { expect, test } from "@playwright/test";
import { mockExchanges, setupVisualTest } from "./fixtures";

// Two faces of the ExchangeDetail header: the clean capture, and the mutated
// capture with the amber "Edited" marker cell. Height clip includes the app
// bar + detail header + tab bar so the whole top chrome is locked in.
test.describe("exchange detail header — instrument strip", () => {
  test("clean (no edited marker)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockExchanges[0].id,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: "claude-sonnet-4-5" }).waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-header-clean.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 200 },
    });
  });

  test("edited (amber marker present)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockExchanges[1].id,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: "gpt-4o" }).waitFor();
    await page.getByText("Edited", { exact: true }).waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-header-edited.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 200 },
    });
  });
});
