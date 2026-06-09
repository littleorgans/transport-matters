import { expect, type Page, test } from "@playwright/test";

// Regression: rapid close/minimize used to land two clicks on the same pane's control button, which
// bubbled a double-click to the pane header's frame gesture — so the canvas FRAMED (zoomed to) the
// pane right as it was being removed (the "frame zoom" flicker, worst at many panes / scale < 1).
// PaneChrome now swallows double-clicks on its controls, so double-clicking a Close/Minimize button
// must never move the camera. Guards the fix end-to-end through the CanvasLabRoute framePane wiring.

async function maxScaleDuring(page: Page, action: () => Promise<void>, ms: number) {
  await page.evaluate(() => {
    const w = window as unknown as { __max: number; __raf: number };
    w.__max = 0;
    const tick = () => {
      const el = document.querySelector('[data-canvas-world="true"]') as HTMLElement | null;
      const s = Number(el?.dataset.canvasScale);
      if (Number.isFinite(s)) w.__max = Math.max(w.__max, s);
      w.__raf = requestAnimationFrame(tick);
    };
    tick();
  });
  await action();
  await page.waitForTimeout(ms);
  return page.evaluate(() => {
    const w = window as unknown as { __max: number; __raf: number };
    cancelAnimationFrame(w.__raf);
    return w.__max;
  });
}

test("double-clicking a pane control never frames the pane (no frame-zoom on rapid close)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");
  await expect(page.getByRole("button", { name: "Close lab-1" })).toBeVisible();

  // Enough panes that the grid is zoomed out (scale < 1), so a frame-to-one-pane is an obvious jump
  // toward 1 rather than a sub-pixel wobble.
  for (let i = 0; i < 12; i += 1) await page.getByRole("button", { name: "Add pane" }).click();
  await page.waitForTimeout(400);
  const overview = Number(
    await page.locator('[data-canvas-world="true"]').getAttribute("data-canvas-scale"),
  );
  expect(overview).toBeLessThan(0.95);

  // Double-click the Close control (the rapid-close gesture that used to frame the pane).
  const maxScale = await maxScaleDuring(
    page,
    () => page.getByRole("button", { name: "Close lab-2", exact: true }).dblclick(),
    450,
  );

  // The camera must stay at the overview — it must NOT zoom toward a single framed pane...
  expect(maxScale).toBeLessThan(overview + 0.05);
  // ...and the pane is actually closed.
  await expect(page.getByRole("button", { name: "Close lab-2", exact: true })).toHaveCount(0);
});
