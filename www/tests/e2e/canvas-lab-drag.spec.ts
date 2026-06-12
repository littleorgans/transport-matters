import { expect, type Locator, type Page, test } from "@playwright/test";

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("expected locator to have a bounding box");
  return box;
}

async function canvasScale(page: Page) {
  return Number(await page.locator('[data-canvas-world="true"]').getAttribute("data-canvas-scale"));
}

// Entry reveal and camera fit animate after goto; measure a baseline only at
// true rest. Two guards because a loaded browser can stall rendering and fake
// stillness mid-glide: first the camera fly must have ended (the framing
// class is removed when the store stops flying), then the box must hold for
// two consecutive 200ms samples.
async function stableBox(page: Page, locator: Locator) {
  await expect(page.locator(".canvas-world--framing")).toHaveCount(0, { timeout: 10000 });
  let previous = await requiredBox(locator);
  let calmStreak = 0;
  await expect
    .poll(
      async () => {
        const current = await requiredBox(locator);
        const moved = Math.hypot(current.x - previous.x, current.y - previous.y);
        previous = current;
        calmStreak = moved < 0.1 ? calmStreak + 1 : 0;
        return calmStreak;
      },
      { timeout: 10000, intervals: [200] },
    )
    .toBeGreaterThanOrEqual(2);
  return previous;
}

async function zoomOut(page: Page, presses: number) {
  const viewport = page.locator(".canvas-viewport");
  const world = page.locator('[data-canvas-world="true"]');
  await viewport.focus();
  for (let index = 0; index < presses; index += 1) await page.keyboard.press("-");
  await expect
    .poll(async () => Number(await world.getAttribute("data-canvas-scale")))
    .toBeLessThan(1);
}

// Seam invariant 3 (doc 19), end to end at a non-1.0 zoom: while the drag is
// LIVE, the lifted pane's screen delta equals the mouse delta. The doubled
// scale conversion regression reads delta/scale here; the skipped one reads
// delta*scale. Measured before release because the release settles the pane
// into its slot (ordering, not positioning).
test("dragging a pane while zoomed out keeps the grabbed header under the pointer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const pane = page.locator('[data-pane-frame="true"]').first();
  const header = pane.locator(".canvas-pane-window__header");
  await expect(header).toBeVisible();
  await zoomOut(page, 4);

  const before = await stableBox(page, header);
  const start = { x: before.x + 36, y: before.y + before.height / 2 };
  const pointerDeltaX = 120;

  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + pointerDeltaX, start.y, { steps: 12 });

  // mid-drag: cursor lock within 3px at scale < 1
  await expect
    .poll(async () => (await requiredBox(header)).x - before.x)
    .toBeGreaterThan(pointerDeltaX - 3);
  expect((await requiredBox(header)).x - before.x).toBeLessThan(pointerDeltaX + 3);

  await page.mouse.up();

  // release settles the pane into a planned slot: it leaves the pointer
  // position and lands on the committed arrangement (no free positioning)
  await expect
    .poll(async () => (await requiredBox(header)).x - before.x, { timeout: 2000 })
    .not.toBeGreaterThan(pointerDeltaX - 3);
});

test("releasing a pane over another pane commits the order and swaps their slots", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const panes = page.locator('[data-pane-frame="true"]');
  await expect(panes.first()).toBeVisible();
  const first = panes.nth(0);
  const second = panes.nth(1);
  await expect(second).toBeVisible();

  const firstBefore = await stableBox(page, first);
  const secondBefore = await stableBox(page, second);
  const header = first.locator(".canvas-pane-window__header");
  const headerBox = await requiredBox(header);

  await page.mouse.move(headerBox.x + 36, headerBox.y + headerBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    secondBefore.x + secondBefore.width / 2,
    secondBefore.y + secondBefore.height / 2,
    { steps: 12 },
  );
  await page.mouse.up();

  // the lifted pane settles into the target's old slot, the target shifts out
  await expect
    .poll(async () => Math.abs((await requiredBox(first)).x - secondBefore.x), { timeout: 2000 })
    .toBeLessThan(3);
  await expect
    .poll(async () => Math.abs((await requiredBox(second)).x - firstBefore.x), { timeout: 2000 })
    .toBeLessThan(3);
});

test("escape cancels a lift and the pane springs home with the order untouched", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const pane = page.locator('[data-pane-frame="true"]').first();
  const header = pane.locator(".canvas-pane-window__header");
  await expect(header).toBeVisible();

  const before = await stableBox(page, header);
  await page.mouse.move(before.x + 36, before.y + before.height / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + 36 + 90, before.y + before.height / 2, { steps: 8 });
  await expect.poll(async () => (await requiredBox(header)).x - before.x).toBeGreaterThan(60);

  await page.keyboard.press("Escape");
  await page.mouse.up();

  // 3px tolerance for the same sub-pixel FLIP drift as the click test; the
  // guarded regression (cancel committing the order) moves a full slot.
  await expect
    .poll(async () => Math.abs((await requiredBox(header)).x - before.x), { timeout: 3000 })
    .toBeLessThan(3);
});

test("a plain header click never moves the pane", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  const pane = page.locator('[data-pane-frame="true"]').first();
  const header = pane.locator(".canvas-pane-window__header");
  await expect(header).toBeVisible();

  // measure the frame, not the header: focus styling can shift the header's
  // box by a border width, while the frame's transform is the pane position
  const before = await stableBox(page, pane);
  const headerBox = await requiredBox(header);
  await page.mouse.move(headerBox.x + 36, headerBox.y + headerBox.height / 2);
  await page.mouse.down();
  await page.mouse.up();

  await page.waitForTimeout(400);
  // 3px tolerance: a focus z-bump re-renders the layer and the size FLIP can
  // re-measure with sub-pixel drift under the lab's fitted scale. The guarded
  // regression (a click lifting or committing a reorder) moves a full slot.
  const after = await stableBox(page, pane);
  expect(Math.abs(after.x - before.x)).toBeLessThan(3);
  expect(Math.abs(after.y - before.y)).toBeLessThan(3);
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
