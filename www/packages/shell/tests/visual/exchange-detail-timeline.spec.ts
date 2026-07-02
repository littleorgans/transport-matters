import { expect, test } from "@playwright/test";
import { mockCodexTimelineOpenId, mockCodexTransportSuccessId, setupVisualTest } from "./fixtures";

test.describe("exchange detail timeline codex semantic states", () => {
  test("completed semantic timeline", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockCodexTransportSuccessId,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: /gpt-5-codex/i }).waitFor();
    await page.getByText("Client sent response.create to open the turn.").waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-timeline-codex.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 900 },
    });
  });

  test("open semantic timeline", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockCodexTimelineOpenId,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: /gpt-5-codex/i }).waitFor();
    await page.getByText("live state").waitFor();
    await page.getByText(/next frame 1/i).waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-timeline-open-codex.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 900 },
    });
  });
});
