import { expect, test } from "@playwright/test";
import {
  mockAnchoredExchanges,
  mockAnchoredSpawnExchangeId,
  mockAnchoredSubagentId,
  setupVisualTest,
} from "./fixtures";

test.describe("ExchangeList — anchored subagent rows", () => {
  test("renders the spawned child track at its parent exchange", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      exchanges: mockAnchoredExchanges,
    });
    await page.goto("/");

    const parentPost = page.getByTestId(`exchange-row-${mockAnchoredExchanges[0].id}`);
    const childHeader = page.getByTestId("track-header-toolu_visual_research");
    const childExchange = page.getByTestId(`exchange-row-${mockAnchoredSubagentId}`);
    const parentSpawn = page.getByTestId(`exchange-row-${mockAnchoredSpawnExchangeId}`);

    await childHeader.waitFor();
    await childExchange.waitFor();
    await parentSpawn.waitFor();

    const postBox = await parentPost.boundingBox();
    const childBox = await childHeader.boundingBox();
    const spawnBox = await parentSpawn.boundingBox();

    expect(postBox).not.toBeNull();
    expect(childBox).not.toBeNull();
    expect(spawnBox).not.toBeNull();
    expect(childBox?.y).toBeGreaterThan(postBox?.y ?? 0);
    expect(childBox?.y).toBeLessThan(spawnBox?.y ?? Number.MAX_SAFE_INTEGER);

    await expect(page.locator("aside")).toHaveScreenshot("exchange-list-anchored-subagent.png", {
      animations: "disabled",
    });
  });
});
