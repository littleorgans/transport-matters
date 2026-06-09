import { expect, type Locator, type Page, test } from "@playwright/test";

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("expected locator to have a bounding box");
  return box;
}

const dockChip = (page: Page) => page.getByRole("button", { name: /Minimized panes/ });

// The dock chip lives in the canvas top band, beneath the lab command bar (bar z2000 > dock z1900).
// The bar's stretched .canvas-command-bar__sections (flex:1) used to capture the chip's clicks even
// where it painted nothing; the fix makes the bar click-through except its real (leading) controls.
// This asserts the chip is the topmost hit target — the regression the review caught.
async function hitTestAtChip(page: Page) {
  const box = await requiredBox(dockChip(page));
  const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  return page.evaluate(({ x, y }) => {
    const el = document.elementFromPoint(x, y);
    return {
      inDock: Boolean(el?.closest(".canvas-viewport-dock")),
      inCommandBarSections: Boolean(el?.closest(".canvas-command-bar__sections")),
    };
  }, point);
}

// "No visual overlap between the dock and command-bar controls": the chip box must not intersect any
// interactive control in the lab bar (controls are leading/left; the dock owns the free trailing end).
async function chipOverlapsAnyBarControl(page: Page) {
  const chipBox = await requiredBox(dockChip(page));
  const controls = page.locator(
    ".canvas-command-bar--lab button, .canvas-command-bar--lab select, .canvas-command-bar--lab a",
  );
  for (let index = 0; index < (await controls.count()); index += 1) {
    const box = await controls.nth(index).boundingBox();
    if (!box) continue;
    const disjoint =
      chipBox.x + chipBox.width <= box.x ||
      box.x + box.width <= chipBox.x ||
      chipBox.y + chipBox.height <= box.y ||
      box.y + box.height <= chipBox.y;
    if (!disjoint) return true;
  }
  return false;
}

// Minimize lab-1 ([-]) and wait for it to dock (close-delay window), so the dock has one entry.
async function minimizeLabOne(page: Page) {
  await expect(page.getByRole("button", { name: "Close lab-1" })).toBeVisible();
  await page.getByRole("button", { name: "Minimize lab-1" }).click();
  await expect(dockChip(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Close lab-1" })).toHaveCount(0);
}

// Open the dock menu, restore lab-1, and assert it is back on the canvas and the dock is empty.
async function openAndRestore(page: Page) {
  await dockChip(page).click();
  await expect(page.getByRole("menu", { name: "Minimized panes" })).toBeVisible();
  await page.getByRole("menuitem", { name: "lab-1" }).click();
  await expect(page.getByRole("button", { name: "Close lab-1" })).toBeVisible();
  await expect(dockChip(page)).toHaveCount(0);
}

test("dock chip is hittable + restores a pane while the lab bar is SHOWN", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");
  // The lab bar is shown by default — this is the occluded state the review flagged.
  await expect(page.getByRole("toolbar", { name: "Canvas lab controls" })).toBeVisible();

  await minimizeLabOne(page);

  const hit = await hitTestAtChip(page);
  expect(hit.inDock).toBe(true);
  expect(hit.inCommandBarSections).toBe(false);
  expect(await chipOverlapsAnyBarControl(page)).toBe(false);

  await openAndRestore(page);
});

test("dock chip is hittable + restores a pane while the lab bar is TAB-HIDDEN", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");

  await minimizeLabOne(page);

  // TAB hides the command bar; the dock lives in the canvas viewport overlay, so it persists.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("toolbar", { name: "Canvas lab controls" })).toHaveCount(0);
  await expect(dockChip(page)).toBeVisible();

  const hit = await hitTestAtChip(page);
  expect(hit.inDock).toBe(true);
  expect(hit.inCommandBarSections).toBe(false);

  await openAndRestore(page);
});
