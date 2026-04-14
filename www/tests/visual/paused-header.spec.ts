import { expect, test } from "@playwright/test";
import { setupVisualTest } from "./fixtures";

// Widths we care about rendering correctly. The frame max-width is 1200px,
// so 1000 is the "narrow" case and 1920 is "extra room". 1200/1440 are the
// typical dev workstation.
const WIDTHS = [1000, 1200, 1440, 1920] as const;

test.describe("paused header — cell layout holds across widths", () => {
  for (const width of WIDTHS) {
    test(`${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await setupVisualTest(page, { armed: true, paused: true });
      await page.goto("/");

      // Wait for the PausedHeader to be in the DOM. The "Paused" label text
      // is unique to this strip.
      await page.getByText("Paused", { exact: true }).waitFor();

      await expect(page).toHaveScreenshot(`paused-${width}.png`, {
        animations: "disabled",
        clip: { x: 0, y: 0, width, height: 260 },
      });
    });
  }
});
