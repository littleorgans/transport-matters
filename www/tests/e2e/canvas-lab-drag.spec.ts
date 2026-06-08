import { expect, type Locator, type Page, test } from "@playwright/test";

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("expected locator to have a bounding box");
  return box;
}

async function canvasScale(page: Page) {
  return Number(await page.locator('[data-canvas-world="true"]').getAttribute("data-canvas-scale"));
}

test("dragging a pane while zoomed out keeps the grabbed header under the pointer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const viewport = page.locator(".canvas-viewport");
  const world = page.locator('[data-canvas-world="true"]');
  const pane = page.locator('[data-pane-frame="true"]').first();
  const header = pane.locator(".canvas-pane-window__header");
  await expect(header).toBeVisible();

  await viewport.focus();
  for (let index = 0; index < 4; index += 1) await page.keyboard.press("-");
  await expect
    .poll(async () => Number(await world.getAttribute("data-canvas-scale")))
    .toBeLessThan(1);

  const before = await requiredBox(header);
  const start = { x: before.x + 36, y: before.y + before.height / 2 };
  const pointerDeltaX = 120;

  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + pointerDeltaX, start.y, { steps: 12 });
  await page.mouse.up();

  const after = await requiredBox(header);
  expect(after.x - before.x).toBeGreaterThan(pointerDeltaX - 4);
  expect(after.x - before.x).toBeLessThan(pointerDeltaX + 4);
});

test("closing a mouse-wheel zoomed pane restores the overview zoom", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const viewport = page.locator(".canvas-viewport");
  await expect(page.getByRole("button", { name: "Close lab-1" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("toolbar", { name: "Canvas lab controls" })).toHaveCount(0);
  const overviewScale = await canvasScale(page);
  const viewportBox = await requiredBox(viewport);

  await page.mouse.move(
    viewportBox.x + viewportBox.width / 2,
    viewportBox.y + viewportBox.height / 2,
  );
  await page.keyboard.down("Shift");
  await page.mouse.wheel(0, -600);
  await page.keyboard.up("Shift");
  await expect.poll(() => canvasScale(page)).toBeGreaterThan(overviewScale + 0.01);

  await page.getByRole("button", { name: "Close lab-1" }).click();
  await expect(page.getByRole("button", { name: "Close lab-1" })).toHaveCount(0);
  await expect
    .poll(async () => Math.abs((await canvasScale(page)) - overviewScale))
    .toBeLessThan(0.001);
});
