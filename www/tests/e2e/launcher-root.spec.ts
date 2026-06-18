import { expect, type Page, test } from "@playwright/test";

test.use({ reducedMotion: "reduce" });

async function openCanvas(page: Page) {
  await page.route("**/v1/runtime-templates", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            name: "research",
            vendors: ["anthropic"],
            required_capabilities: [],
            recommended_model: { default: { harness: "claude", vendor: "anthropic" } },
          },
        ],
      }),
    }),
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();
}

test("⌘K root lists the five domains with agents collapsed; ↵ enters Agents", async ({ page }) => {
  await openCanvas(page);
  await page.keyboard.press("Meta+k");
  await expect(page.getByRole("combobox")).toBeVisible();

  // Domains-first root: the five enterable domains, the count, the search hint.
  const titles = page.locator(".launcher__row-title");
  for (const name of ["Agents", "Canvas", "Workdir", "Settings", "Sessions"]) {
    await expect(titles.filter({ hasText: new RegExp(`^${name}$`) })).toBeVisible();
  }
  await expect(page.getByText("5 domains")).toBeVisible();
  await expect(page.getByText("TYPE TO SEARCH ALL")).toBeVisible();
  // Agents are collapsed behind the Agents domain — no native rows spill at root.
  await expect(titles.filter({ hasText: "Codex" })).toHaveCount(0);

  // ↵ on the auto-highlighted Agents domain enters the Agents scope.
  await page.keyboard.press("Enter");
  await expect(titles.filter({ hasText: "Codex" })).toBeVisible();
  await expect(titles.filter({ hasText: "Claude" })).toBeVisible();
});

test("⌘A jumps straight into Agents from cold", async ({ page }) => {
  await openCanvas(page);
  await page.keyboard.press("Meta+a");
  const titles = page.locator(".launcher__row-title");
  await expect(titles.filter({ hasText: "Codex" })).toBeVisible();
  await expect(titles.filter({ hasText: "Claude" })).toBeVisible();
});

test("typing at root flat-searches across domains and surfaces agents", async ({ page }) => {
  await openCanvas(page);
  await page.keyboard.press("Meta+k");
  await expect(page.getByRole("combobox")).toBeVisible();

  await page.getByRole("combobox").pressSequentially("research");

  // The specialist agent surfaces inline (flat search), and the domain entries
  // are replaced by results.
  const titles = page.locator(".launcher__row-title");
  await expect(titles.filter({ hasText: /^research$/ })).toBeVisible();
  await expect(titles.filter({ hasText: "Workdir" })).toHaveCount(0);
});
