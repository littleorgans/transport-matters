import { expect, type Page, test } from "@playwright/test";
import { FRONTEND_STORAGE_KEYS } from "../../src/stores/persistence";
import { seedCanvasExchangePane, setupCanvasApis } from "../visual/fixtures";
import { pressMod } from "./keyboard";

test.use({ reducedMotion: "reduce" });

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
