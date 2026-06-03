import { expect, type Locator, type Page, test } from "@playwright/test";
import { mockExchanges, setupVisualTest } from "../visual/fixtures";

// Real-browser guards for the FullscreenOverlay. Two bugs shipped that jsdom
// cannot reproduce because they depend on the compiled stylesheet:
//  1. `relative` in the base class beat the conditional `fixed` (Tailwind
//     emits `.relative` after `.fixed`), so the overlay never covered the
//     viewport.
//  2. The inline wrapper broke the flex height chain a `flex-1 overflow-y-auto`
//     pane relies on, so content could not scroll (inline or fullscreen).
async function expectCoversViewport(page: Page, overlay: Locator) {
  await expect(overlay).toBeVisible();
  const position = await overlay.evaluate((el) => getComputedStyle(el).position);
  expect(position).toBe("fixed");
  const box = await overlay.boundingBox();
  const vp = page.viewportSize();
  if (!box || !vp) throw new Error("missing overlay box or viewport");
  expect(box.x).toBeLessThanOrEqual(1);
  expect(box.y).toBeLessThanOrEqual(1);
  expect(box.width).toBeGreaterThanOrEqual(vp.width - 1);
  expect(box.height).toBeGreaterThanOrEqual(vp.height - 1);
}

// A scroll region must exist inside the overlay and be bounded by the
// viewport, otherwise tall payloads clip / push the page.
async function expectScrollableWithinViewport(overlay: Locator) {
  const scroller = overlay.locator(".overflow-y-auto").first();
  await expect(scroller).toBeVisible();
  const overflowY = await scroller.evaluate((el) => getComputedStyle(el).overflowY);
  expect(["auto", "scroll"]).toContain(overflowY);
  const metrics = await scroller.evaluate((el) => ({
    clientHeight: el.clientHeight,
    innerHeight: window.innerHeight,
  }));
  expect(metrics.clientHeight).toBeGreaterThan(0);
  expect(metrics.clientHeight).toBeLessThanOrEqual(metrics.innerHeight + 1);
}

test.describe("fullscreen overlay covers the viewport and scrolls", () => {
  test("INSPECT expand covers viewport, scrolls, and Esc closes", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    await setupVisualTest(page, {
      selectedExchangeId: mockExchanges[0].id,
      paused: false,
      armed: false,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: "claude-sonnet-4-5" }).waitFor();

    await page.getByRole("button", { name: "Open inspect fullscreen" }).click();
    const overlay = page.locator('button[aria-label="Close inspect fullscreen"]').locator("..");
    await expectCoversViewport(page, overlay);
    await expectScrollableWithinViewport(overlay);

    await page.keyboard.press("Escape");
    await expect(page.locator('button[aria-label="Close inspect fullscreen"]')).toHaveCount(0);
  });

  test("breakpoint editor: inline is layout-neutral, expand covers + scrolls", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    await setupVisualTest(page, { armed: true, paused: true });
    await page.goto("/");
    await page.getByText("Paused", { exact: true }).waitFor();

    // Inline: nothing should overflow horizontally (the broken row-flex
    // wrapper pushed content off to the right).
    const noHOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
    );
    expect(noHOverflow).toBe(true);
    await page.screenshot({ path: "test-results/overlay-editor-inline.png" });

    for (const tab of ["messages", "overlay", "raw"] as const) {
      await page.getByRole("button", { name: tab, exact: true }).click();
      await page.getByRole("button", { name: `Open ${tab} fullscreen` }).click();
      const overlay = page.locator(`button[aria-label="Close ${tab} fullscreen"]`).locator("..");
      await expectCoversViewport(page, overlay);
      await expectScrollableWithinViewport(overlay);
      if (tab === "messages") {
        await page.screenshot({ path: "test-results/overlay-editor-expanded.png" });
      }
      await page.keyboard.press("Escape");
      await expect
        .poll(() => overlay.evaluate((el) => getComputedStyle(el).display))
        .toBe("contents");
    }
  });
});
