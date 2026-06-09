import { expect, type Page, test } from "@playwright/test";

// TEMPORARY reproduction harness for the "minimize/close frames the pane for a moment" report.
// Samples the world transform (scale/pan) + focused pane every animation frame during a teardown,
// then prints the timeline so we can see whether the camera moves (frame-in) and which pane is
// focused mid-close. Delete after diagnosis.

async function startSampling(page: Page) {
  await page.evaluate(() => {
    (window as unknown as { __samples: unknown[] }).__samples = [];
    const tick = () => {
      const world = document.querySelector('[data-canvas-world="true"]') as HTMLElement | null;
      const focused = document.querySelector('[data-pane-frame="true"][data-focused="true"]');
      const framed = document.querySelector('.canvas-pane-window[data-state="framed"]');
      (window as unknown as { __samples: unknown[] }).__samples.push({
        t: Math.round(performance.now()),
        scale: world?.dataset.canvasScale,
        transform: world?.style.transform,
        focused: focused?.getAttribute("data-pane-id") ?? null,
        framed: Boolean(framed),
      });
      (window as unknown as { __raf: number }).__raf = requestAnimationFrame(tick);
    };
    tick();
  });
}

async function dumpSamples(page: Page, label: string) {
  const samples = await page.evaluate(() => {
    cancelAnimationFrame((window as unknown as { __raf: number }).__raf);
    return (window as unknown as { __samples: { scale: string }[] }).__samples;
  });
  const scales = samples.map((s) => Number(s.scale));
  const min = Math.min(...scales);
  const max = Math.max(...scales);
  console.log(`\n### ${label}: ${samples.length} frames, scale min=${min} max=${max}`);
  // Print only transitions (where scale or focused/framed changed) to keep it readable.
  let prev = "";
  for (const s of samples) {
    const key = `${s.scale}|${(s as { focused: string }).focused}|${(s as { framed: boolean }).framed}`;
    if (key !== prev) {
      console.log(
        `  t=${(s as { t: number }).t} scale=${s.scale} focused=${(s as { focused: string }).focused} framed=${(s as { framed: boolean }).framed}`,
      );
      prev = key;
    }
  }
}

test("repro: minimize/close transforms", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas-lab");
  await expect(page.getByRole("button", { name: "Close lab-1" })).toBeVisible();

  // Scenario A: default close (fit-to-content on, ~1:1).
  await startSampling(page);
  await page.getByRole("button", { name: "Close lab-1" }).click();
  await page.waitForTimeout(700);
  await dumpSamples(page, "A close lab-1 (default fit)");

  // Scenario B: minimize.
  await startSampling(page);
  await page.getByRole("button", { name: "Minimize lab-2" }).click();
  await page.waitForTimeout(700);
  await dumpSamples(page, "B minimize lab-2 (default fit)");

  // Scenario C: add many panes so fit zooms out (<1), then close one.
  for (let i = 0; i < 14; i += 1) await page.getByRole("button", { name: "Add pane" }).click();
  await page.waitForTimeout(400);
  await startSampling(page);
  const closeButtons = page.getByRole("button", { name: /^Close lab-/ });
  await closeButtons.first().click();
  await page.waitForTimeout(700);
  await dumpSamples(page, "C close one of many (zoomed out)");

  // Scenario D: minimize one of many.
  await startSampling(page);
  await page
    .getByRole("button", { name: /^Minimize lab-/ })
    .first()
    .click();
  await page.waitForTimeout(700);
  await dumpSamples(page, "D minimize one of many (zoomed out)");
});
