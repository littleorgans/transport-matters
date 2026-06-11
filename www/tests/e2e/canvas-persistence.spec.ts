import { expect, type Locator, type Page, test } from "@playwright/test";

interface PersistedPaneRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

type PersistedPaneRects = Record<string, PersistedPaneRect>;

const sessions = [
  sessionSummary("alpha-session", "Alpha session"),
  sessionSummary("beta-session", "Beta session"),
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const resetFlag = "transport-matters.canvas-persistence-e2e-reset";
    if (sessionStorage.getItem(resetFlag)) return;
    localStorage.removeItem("transport-matters-canvas");
    sessionStorage.setItem(resetFlag, "true");
  });
});

function sessionSummary(sessionId: string, title: string) {
  return {
    session_id: sessionId,
    provider: "anthropic",
    cli: "claude",
    run_id: `run-${sessionId}`,
    cwd: "/tmp/transport-matters",
    workspace_slug: "transport-matters",
    workspace_hash: "workspace-hash",
    native_session_id: null,
    minted: false,
    source_descriptor: null,
    home_dir: null,
    owner: "local",
    status: "active",
    title,
    parent_session_id: null,
    forked_at_seq: null,
    started_at: "2026-06-11T00:00:00Z",
    created_at: "2026-06-11T00:00:00Z",
    updated_at: "2026-06-11T00:00:00Z",
  };
}

async function mockSessionApi(page: Page) {
  await page.route("**/api/sessions/*/events/stream**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    }),
  );
  await page.route("**/api/sessions/*/events?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ events: [], next_from_seq: null }),
    }),
  );
  await page.route("**/api/sessions?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sessions),
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
  const stored = await page.evaluate(() => localStorage.getItem("transport-matters-canvas"));
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

function requiredStoredRect(rects: PersistedPaneRects, paneId: string): PersistedPaneRect {
  const rect = rects[paneId];
  if (!rect) throw new Error(`expected persisted rect for ${paneId}`);
  return rect;
}

function expectBoxNearRect(box: PersistedPaneRect, rect: PersistedPaneRect) {
  const positionTolerance = 12;
  const sizeTolerance = 24;
  expect(Math.abs(box.x - rect.x)).toBeLessThanOrEqual(positionTolerance);
  expect(Math.abs(box.y - rect.y)).toBeLessThanOrEqual(positionTolerance);
  expect(Math.abs(box.width - rect.width)).toBeLessThanOrEqual(sizeTolerance);
  expect(Math.abs(box.height - rect.height)).toBeLessThanOrEqual(sizeTolerance);
}

test("product canvas persists arranged panes and dock state across reload", async ({ page }) => {
  await mockSessionApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");

  await expect(page.getByRole("toolbar", { name: "Canvas commands" })).toBeVisible();
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
  const savedAlphaRect = requiredStoredRect(savedPaneRects, "transcript:alpha-session");

  await page.reload();

  const reloadedAlpha = paneByTitle(page, "Alpha session");
  await expect(reloadedAlpha).toBeVisible();
  await expect(page.getByRole("button", { name: "Unexpand Alpha session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close Beta session" })).toHaveCount(0);
  await expect(dockChip(page)).toBeVisible();
  await expect.poll(() => storedPaneRects(page)).toEqual(savedPaneRects);
  expectBoxNearRect(await requiredBox(reloadedAlpha), savedAlphaRect);

  await dockChip(page).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu", { name: "Minimized panes" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Beta session", exact: true })).toBeVisible();
});
