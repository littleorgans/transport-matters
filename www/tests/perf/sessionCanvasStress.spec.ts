import { expect, type Locator, type Page, test } from "@playwright/test";

const STRESS_P95_THRESHOLD_MS = 50;

test("captures bounded p95 frame time across pane motion operations", async ({ page }) => {
  await page.goto("/canvas?stress=1");
  await expect(page.getByText("FLIP stress harness")).toBeVisible();

  const readout = page.locator(".canvas-stress-readout");
  await expect(readout).toContainText("Stable synthetic panes: 4");

  await clickCount(page, "30");
  await expect(readout).toContainText("Stable synthetic panes: 30");
  await expectFrameSample(readout, "spawn");

  await clickCount(page, "8");
  await expect(readout).toContainText("Stable synthetic panes: 8");
  await expectFrameSample(readout, "close");

  const pane = page.locator("[data-pane-id='stress-1']");
  await pane.click();
  await expectFrameSample(readout, "focus");

  await dragBy(page, pane.locator("[data-pane-drag-handle='true']"), 48, 28);
  await expectFrameSample(readout, "drag");

  await dragBy(page, pane.locator("[data-pane-resize-handle='true']"), 36, 24);
  await expectFrameSample(readout, "resize");

  const canvas = page.getByRole("application", { name: "Session canvas stress harness" });
  await canvas.focus();
  await page.keyboard.press("Alt+ArrowRight");
  await expectFrameSample(readout, "pan");

  await page.keyboard.press("=");
  await expectFrameSample(readout, "zoom");
});

async function clickCount(page: Page, count: string): Promise<void> {
  await page.getByRole("button", { exact: true, name: count }).click();
}

async function dragBy(page: Page, target: Locator, deltaX: number, deltaY: number): Promise<void> {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + deltaX, startY + deltaY, { steps: 4 });
  await page.mouse.up();
}

async function expectFrameSample(readout: Locator, action: string): Promise<void> {
  await expect(readout).toHaveAttribute("data-stress-action", action, { timeout: 4_000 });
  await expect
    .poll(async () => Number(await readout.getAttribute("data-stress-frames")))
    .toBeGreaterThan(0);
  const p95 = Number(await readout.getAttribute("data-stress-p95-frame"));
  expect(p95).toBeGreaterThan(0);
  expect(p95).toBeLessThanOrEqual(STRESS_P95_THRESHOLD_MS);
}
