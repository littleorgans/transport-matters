import { expect, test } from "@playwright/test";

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
