import { expect, type Locator, type Page, test } from "@playwright/test";

interface PersistedPaneRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

type PersistedPaneRects = Record<string, PersistedPaneRect>;

// Slice 6 namespaces the canvas cache by canvasId. The product /canvas route (no
// space/worktree/hash params) resolves to the "direct-local" canvas, so its
// persisted state lives under this namespaced key, not the bare legacy key.
const CANVAS_STORE_KEY = "transport-matters-canvas:direct-local";

const sessions = [
  sessionSummary("alpha-session", "Alpha session"),
  sessionSummary("beta-session", "Beta session"),
];

// The canvas frames/centers panes with a 320ms `.canvas-world--framing` transform
// transition (zeroed under reduced motion). Emulating reduced motion makes that
// transform apply instantly, so boundingBox reads are the settled position (no
// mid-animation flake) and minimize→dock is immediate.
test.use({ reducedMotion: "reduce" });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const resetFlag = "transport-matters.canvas-persistence-e2e-reset";
    if (sessionStorage.getItem(resetFlag)) return;
    // Clear both the bare legacy key and any per-canvasId namespaced keys so each
    // test starts clean (but not on the in-test reload — the flag guards that).
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("transport-matters-canvas")) localStorage.removeItem(key);
    }
    sessionStorage.setItem(resetFlag, "true");
  });
});

function sessionSummary(sessionId: string, title: string) {
  return {
    sessionId,
    workspaceId: "transport-matters/workspace-hash",
    title,
    status: "active",
    provider: "anthropic",
    cli: "claude",
    createdAt: "2026-06-11T00:00:00Z",
    lastActivityAt: "2026-06-11T00:00:00Z",
    purpose: "user_history",
    visibility: "user_visible",
    lineage: {
      parentSessionId: null,
      forkedAtSeq: null,
      forkedAtTurn: null,
    },
    turnCount: 0,
    inheritedTurnCount: 0,
    lastMessagePreview: null,
  };
}

async function mockSessionApi(page: Page) {
  await page.route("**/v1/sessions/*/events/stream**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    }),
  );
  await page.route("**/v1/sessions/*/events?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ events: [], nextFromSeq: null }),
    }),
  );
  await page.route("**/v1/sessions?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: sessions, nextCursor: null }),
    }),
  );
}

function paneByTitle(page: Page, title: string) {
  return page.locator(".canvas-pane-window", {
    has: page.getByRole("heading", { name: title }),
  });
}

const dockChip = (page: Page) => page.getByRole("button", { name: /Minimized panes/ });

async function storedPaneRects(page: Page): Promise<PersistedPaneRects> {
  const stored = await page.evaluate((key) => localStorage.getItem(key), CANVAS_STORE_KEY);
  if (!stored) throw new Error("expected persisted canvas storage to exist");

  const parsed = JSON.parse(stored) as { state?: { paneRects?: PersistedPaneRects } };
  if (!parsed.state?.paneRects) throw new Error("expected persisted pane rects to exist");
  return parsed.state.paneRects;
}

async function requiredBox(locator: Locator): Promise<PersistedPaneRect> {
  const box = await locator.boundingBox();
  if (!box) throw new Error("expected locator to have a bounding box");
  return box;
}

const VIEWPORT = { width: 1280, height: 900 };

function expectPaneOnScreen(box: PersistedPaneRect) {
  // The restored pane renders as a real, substantial pane whose centre is on
  // screen. We do NOT pixel-match its screen geometry across the reload: reload
  // hydration re-runs a non-persisted, browser-dependent auto-fit (translate AND
  // a small zoom), so absolute coords legitimately shift. Exact arrangement
  // persistence is asserted separately and far more strictly via the
  // storedPaneRects toEqual below; this guards against a pane that restores in
  // state but renders collapsed or off-screen.
  expect(box.width).toBeGreaterThan(200);
  expect(box.height).toBeGreaterThan(120);
  const centreX = box.x + box.width / 2;
  const centreY = box.y + box.height / 2;
  expect(centreX).toBeGreaterThan(0);
  expect(centreX).toBeLessThan(VIEWPORT.width);
  expect(centreY).toBeGreaterThan(0);
  expect(centreY).toBeLessThan(VIEWPORT.height);
}

test("product canvas persists arranged panes and dock state across reload", async ({ page }) => {
  await mockSessionApi(page);
  await page.setViewportSize(VIEWPORT);
  await page.goto("/canvas");

  // Zero-chrome canvas: readiness is the route shell + a populated session
  // picker row, not the removed "Canvas commands" toolbar (re-homed into the ⌘K
  // command center). Waiting for the row (which renders only after sessions
  // load) lets the viewport settle before we arrange panes.
  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  await expect(page.locator(".canvas-picker__row", { hasText: "Alpha session" })).toBeVisible();
  await page.locator(".canvas-picker__row", { hasText: "Alpha session" }).click();
  await page.locator(".canvas-picker__row", { hasText: "Beta session" }).click();

  const alphaPane = paneByTitle(page, "Alpha session");
  await expect(alphaPane).toBeVisible();
  await expect(paneByTitle(page, "Beta session")).toBeVisible();

  await page.getByRole("button", { name: "Expand Alpha session" }).click();
  await expect(page.getByRole("button", { name: "Unexpand Alpha session" })).toBeVisible();

  await page.getByRole("button", { name: "Minimize Beta session" }).click();
  await expect(page.getByRole("button", { name: "Close Beta session" })).toHaveCount(0);
  await expect(dockChip(page)).toBeVisible();
  const savedPaneRects = await storedPaneRects(page);

  await page.reload();

  const reloadedAlpha = paneByTitle(page, "Alpha session");
  await expect(reloadedAlpha).toBeVisible();
  await expect(page.getByRole("button", { name: "Unexpand Alpha session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close Beta session" })).toHaveCount(0);
  await expect(dockChip(page)).toBeVisible();
  await expect.poll(() => storedPaneRects(page)).toEqual(savedPaneRects);
  expectPaneOnScreen(await requiredBox(reloadedAlpha));

  await dockChip(page).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu", { name: "Minimized panes" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Beta session", exact: true })).toBeVisible();
});

test("imports a pre-Spaces legacy canvas (bare key) into the default canvas on first load", async ({
  page,
}) => {
  await mockSessionApi(page);
  await page.setViewportSize(VIEWPORT);
  // Seed the PRE-Slice-6 single-canvas blob under the bare legacy key. The store's
  // module-load import must fold it into the namespaced default canvas BEFORE the
  // persist middleware writes an empty default — otherwise the no-overwrite guard
  // skips the legacy blob on the in-action import and the canvas is silently lost.
  await page.addInitScript(() => {
    localStorage.setItem(
      "transport-matters-canvas",
      JSON.stringify({
        version: 1,
        state: {
          contentRefs: {
            "session-picker": { kind: "session-picker", owner: "local" },
            "transcript:alpha-session": {
              kind: "session-timeline",
              owner: "local",
              sessionId: "alpha-session",
              title: "Alpha session",
            },
          },
          paneRects: {
            "session-picker": { x: 32, y: 32, width: 380, height: 520 },
            "transcript:alpha-session": { x: 444, y: 32, width: 600, height: 520 },
          },
          order: ["session-picker", "transcript:alpha-session"],
          docked: [],
          fitToContent: true,
          expandedPaneId: null,
        },
      }),
    );
  });

  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();

  // The legacy transcript pane rehydrated onto the canvas → the import ran.
  await expect(paneByTitle(page, "Alpha session")).toBeVisible();
  // The bare legacy key is consumed exactly once; the data now lives namespaced.
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("transport-matters-canvas")))
    .toBeNull();
  await expect
    .poll(() => page.evaluate((key) => localStorage.getItem(key), CANVAS_STORE_KEY))
    .not.toBeNull();
});
