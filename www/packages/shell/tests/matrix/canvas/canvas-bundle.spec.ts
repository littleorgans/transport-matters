import { expect, test } from "@playwright/test";
import { seedCanvasExchangePane, setupCanvasApis } from "../../visual/fixtures";

test.use({ reducedMotion: "reduce" });

// The REAL built canvas bundle served by `vite preview` at its production
// base "/canvas". The entry runs mountWindowChrome() and
// bootstrapThemeTokens() before render, so a green boot proves the
// per-entry wiring; the asset checks prove every URL respects the base.
test("the built canvas bundle boots at /canvas with assets under the base", async ({ page }) => {
  const missingAssets: string[] = [];
  const servedAssets: string[] = [];
  page.on("response", (response) => {
    const { pathname } = new URL(response.url());
    if (!pathname.startsWith("/canvas/assets/")) return;
    (response.ok() ? servedAssets : missingAssets).push(pathname);
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");

  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  expect(missingAssets).toEqual([]);
  expect(servedAssets.length).toBeGreaterThan(0);
});

// The canvas bundle must OWN its reset environment. On the pre-P6 shared
// origin the inspector's Tailwind entry injected the preflight globally;
// standalone, the canvas vendors it (src/styles/reset.css). Pins the
// load-bearing rules: border-box sizing (pane geometry is planned in
// border-box; without it the grid layout and pane borders break) and
// `[hidden] { display:none !important }` (CommandBarSections hides its
// inactive group via the hidden attribute, which author display rules
// otherwise override — the LAYOUT toggle goes inert).
test("the canvas bundle carries its own reset environment", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();

  const environment = await page.evaluate(() => {
    const shell = document.querySelector(".canvas-route-shell");
    // The exact fight from the lab regression, reachable from /canvas:
    // .canvas-command-bar__group sets `display: flex`, which beats the UA
    // [hidden] rule unless the preflight's !important rule is present.
    // (CommandBarSections itself only renders on /canvas-lab, which vite
    // preview cannot serve — the FastAPI integration test covers that page.)
    const probe = document.createElement("div");
    probe.className = "canvas-command-bar__group";
    probe.hidden = true;
    document.body.append(probe);
    const hiddenProbeDisplay = getComputedStyle(probe).display;
    probe.remove();
    return {
      bodyMargin: getComputedStyle(document.body).margin,
      shellBoxSizing: shell ? getComputedStyle(shell).boxSizing : null,
      hiddenProbeDisplay,
    };
  });

  expect(environment.bodyMargin).toBe("0px");
  expect(environment.shellBoxSizing).toBe("border-box");
  expect(environment.hiddenProbeDisplay).toBe("none");
});

// The engine's structural CSS must ship inside the canvas bundle. On the
// shared origin the inspector's Tailwind pass generated the engine's
// utility classes; standalone they are owned CSS (engine/react/
// pane-frame.css). Without position:absolute, panes stack in static flow
// (each renders at planned y + the previous pane's height); without the
// full-height body, pane content does not fill the planned rect. Dock
// restore drives the same replan path spawns use (planSpawnedPaneLayout).
test("dock-restore replans a packed grid with full-height panes", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await setupCanvasApis(page);
  await seedCanvasExchangePane(page);
  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();

  const dockChip = page.getByRole("button", { name: /Minimized panes/ });
  await expect(async () => {
    await page.getByRole("button", { name: "Minimize Session picker" }).click();
    await expect(dockChip).toBeVisible({ timeout: 1500 });
  }).toPass({ timeout: 15000 });
  await dockChip.click();
  await page.getByRole("menuitem", { name: "Session picker", exact: true }).click();

  await expect(page.locator("[data-pane-frame='true']")).toHaveCount(2);
  await expect(async () => {
    const geometry = await page.evaluate(() =>
      [...document.querySelectorAll("[data-pane-frame='true']")].map((frame) => {
        const rect = frame.getBoundingClientRect();
        const body = frame.querySelector(".pane-frame__body")?.getBoundingClientRect();
        return { x: rect.x, y: rect.y, w: rect.width, h: rect.height, bodyH: body?.height ?? 0 };
      }),
    );
    expect(geometry).toHaveLength(2);
    const [a, b] = geometry;
    if (!a || !b) throw new Error("expected two frames");
    // Packed into one row: equal y, side by side, no overlap.
    expect(Math.abs(a.y - b.y)).toBeLessThan(2);
    const [left, right] = a.x < b.x ? [a, b] : [b, a];
    expect(right.x).toBeGreaterThanOrEqual(left.x + left.w);
    // The gesture body fills the planned rect (the h-full replacement).
    for (const frame of geometry) {
      expect(Math.abs(frame.bodyH - frame.h)).toBeLessThan(2);
    }
  }).toPass({ timeout: 10000 });
});

// Desktop smoke: the desktop shell loads this same bundle at /canvas
// (rendererUrlForPort's default; desktop is verification, not
// modification). With the desktop bridge present, the host chrome mounts
// the window drag strip that only renders inside the Electron shell.
test("desktop smoke: canvas boots under the desktop bridge with window chrome", async ({
  page,
}) => {
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).transportMattersDesktop = {};
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");

  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  await expect(page.locator(".window-drag-region")).toHaveCount(1);
});
