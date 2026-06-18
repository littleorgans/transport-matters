import { expect, type Page, type Route, test } from "@playwright/test";
import { FRONTEND_STORAGE_KEYS } from "../../src/stores/persistence";
import { mockExchangeDetails, mockExchanges, mockVisualRunId } from "../visual/fixtures";
import { pressMod } from "./keyboard";

test.use({ reducedMotion: "reduce" });

async function setupCanvasApis(page: Page) {
  await page.route((url) => url.pathname.startsWith("/api/"), fulfillApiRoute);
  await page.route((url) => url.pathname.startsWith("/v1/"), fulfillV1Route);
}

async function fulfillApiRoute(route: Route) {
  const path = new URL(route.request().url()).pathname;

  if (path === "/api/meta") {
    return route.fulfill({
      json: {
        cwd: "/Users/alphab/Dev/LLM/DEV/helioy/transport-matters",
        workspace_id: "helioy/transport-matters",
        run_id: mockVisualRunId,
      },
    });
  }

  if (path === "/api/breakpoint/status") {
    return route.fulfill({ json: { mode: "off", paused_flows: [] } });
  }

  return route.fulfill({ json: {} });
}

async function fulfillV1Route(route: Route) {
  const path = new URL(route.request().url()).pathname;

  if (path === "/v1/runtime-templates") {
    return route.fulfill({
      json: {
        items: [
          {
            name: "research",
            vendors: ["anthropic"],
            required_capabilities: [],
            recommended_model: { default: { harness: "claude", vendor: "anthropic" } },
          },
        ],
      },
    });
  }

  if (path === `/v1/runs/${mockVisualRunId}/exchanges`) {
    return route.fulfill({ json: mockExchanges });
  }

  const detailMatch = path.match(/^\/v1\/runs\/([^/]+)\/exchanges\/([^/]+)$/);
  if (detailMatch) {
    const [, runId, encodedId] = detailMatch;
    const detail = mockExchangeDetails[decodeURIComponent(encodedId ?? "")];
    if (runId === mockVisualRunId && detail) return route.fulfill({ json: detail });
    return route.fulfill({ status: 404, json: { error: "not found" } });
  }

  return route.fulfill({ json: {} });
}

async function seedCanvasExchangePane(page: Page) {
  await page.addInitScript(
    ({
      storageKey,
      runId,
      exchangeId,
    }: {
      storageKey: string;
      runId: string;
      exchangeId: string;
    }) => {
      const exchangePaneId = `exchange:${runId}:${exchangeId}`;
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          version: 1,
          state: {
            contentRefs: {
              "session-picker": { kind: "session-picker", owner: "local" },
              [exchangePaneId]: {
                kind: "provider-exchange",
                owner: "local",
                sessionId: "visual-session",
                runId,
                exchangeId,
                initialView: "inspect",
              },
            },
            paneRects: {
              "session-picker": { x: 32, y: 32, width: 380, height: 520 },
              [exchangePaneId]: { x: 444, y: 32, width: 760, height: 700 },
            },
            order: ["session-picker", exchangePaneId],
            docked: [],
            fitToContent: true,
            expandedPaneId: null,
          },
        }),
      );
    },
    {
      storageKey: FRONTEND_STORAGE_KEYS.canvasStore,
      runId: mockVisualRunId,
      exchangeId: mockExchanges[0].id,
    },
  );
}

async function openDesktopCanvas(page: Page) {
  await page.setViewportSize({ width: 1280, height: 900 });
  await setupCanvasApis(page);
  await seedCanvasExchangePane(page);
  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();
}

async function currentCanvasScale(page: Page): Promise<number> {
  const raw = await page.locator("[data-canvas-world='true']").getAttribute("data-canvas-scale");
  return Number(raw ?? "NaN");
}

function gestureModifierRow(page: Page, modifier: "Shift" | "Space") {
  return page.locator(".launcher__row").filter({
    hasText: `Canvas gesture modifier: ${modifier}`,
  });
}

async function expectCurrentGestureModifier(page: Page, modifier: "Shift" | "Space") {
  await pressMod(page, ",");
  await expect(page.getByRole("combobox")).toBeVisible();
  await expect(gestureModifierRow(page, modifier)).toContainText("Current");
}

async function focusCanvasGestureSurface(page: Page) {
  const surface = page.locator("[data-canvas-gesture-surface='true']");
  await expect(surface).toBeVisible();
  await surface.focus();
  await page.mouse.move(1100, 800);
}

test("desktop registry toggles command center with $mod+K", async ({ page }) => {
  await openDesktopCanvas(page);

  await pressMod(page, "k");
  await expect(page.getByRole("combobox")).toBeVisible();

  await pressMod(page, "k");
  await expect(page.getByRole("combobox")).toHaveCount(0);
});

test("desktop Escape order is palette, dock, fullscreen", async ({ page }) => {
  await openDesktopCanvas(page);
  const dockChip = page.getByRole("button", { name: /Minimized panes/ });
  const fullscreenClose = page.getByRole("button", { name: /close inspect fullscreen/i });

  await page.getByRole("button", { name: "Minimize Session picker" }).click();
  await expect(dockChip).toBeVisible();

  await page.getByRole("button", { name: /open inspect fullscreen/i }).click();
  await expect(fullscreenClose).toBeVisible();

  await dockChip.click();
  await expect(dockChip).toHaveAttribute("aria-expanded", "true");

  await pressMod(page, "k");
  await expect(page.getByRole("combobox")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(dockChip).toHaveAttribute("aria-expanded", "true");
  await expect(fullscreenClose).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dockChip).toHaveAttribute("aria-expanded", "false");
  await expect(fullscreenClose).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(fullscreenClose).toHaveCount(0);
});

test("settings persists the Space canvas gesture modifier and keeps Shift as the fresh default", async ({
  page,
}) => {
  await openDesktopCanvas(page);

  await expectCurrentGestureModifier(page, "Shift");
  await gestureModifierRow(page, "Space").click();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate((storageKey) => {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return null;
        return (JSON.parse(raw) as { state?: { canvasGestureModifier?: string } }).state
          ?.canvasGestureModifier;
      }, FRONTEND_STORAGE_KEYS.keymapStore),
    )
    .toBe("Space");

  await focusCanvasGestureSurface(page);
  const beforeShiftWheel = await currentCanvasScale(page);
  await page.keyboard.down("Shift");
  await page.mouse.wheel(0, -240);
  await page.keyboard.up("Shift");
  await expect.poll(() => currentCanvasScale(page)).toBe(beforeShiftWheel);

  await page.keyboard.down("Space");
  await page.mouse.wheel(0, -240);
  await page.keyboard.up("Space");
  await expect.poll(() => currentCanvasScale(page)).toBeGreaterThan(beforeShiftWheel);

  await page.reload();
  await expect(page.locator(".canvas-route-shell")).toBeVisible();
  await expectCurrentGestureModifier(page, "Space");
});
