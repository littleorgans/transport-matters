import { expect, test } from "@playwright/test";
import { seedCanvasExchangePane, setupCanvasApis } from "./fixtures";

test.use({ reducedMotion: "reduce" });

// The codex fixture exercises every surface the viewer forks from the
// inspector detail: codex telemetry chips, the timeline label, request
// messages and tools, response content, and transport frames.
const CODEX_EXCHANGE_ID = "ffff0000-1111-2222-3333-444455556666";

test("canvas provider-exchange pane renders the Ark exchange viewer", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await setupCanvasApis(page);
  await seedCanvasExchangePane(page, {
    exchangeId: CODEX_EXCHANGE_ID,
    // Expanded (hero) pane: the whole viewer, including the tab row's
    // fullscreen affordance, stays inside the viewport for the snapshot.
    expanded: true,
  });
  await page.goto("/canvas");

  const viewer = page.locator(".canvas-exchange");
  await expect(viewer).toBeVisible();
  await expect(viewer.getByRole("heading", { level: 2 })).toContainText("codex");
  await expect(viewer.getByRole("button", { name: /open inspect fullscreen/i })).toBeVisible();

  await expect(viewer).toHaveScreenshot("canvas-exchange-viewer.png");
});
