import { expect, test } from "@playwright/test";

// Settled, unanimated transforms so boundingBox reads are deterministic.
test.use({ reducedMotion: "reduce" });

// A specialist fleet large enough to overflow the palette's bounded list, so
// arrowing down must scroll the active option into view.
const items = Array.from({ length: 16 }, (_, index) => ({
  name: `specialist-${index}`,
  vendors: ["anthropic"],
  required_capabilities: [],
  recommended_model: { default: { harness: "claude", vendor: "anthropic" } },
}));

test("arrowing keeps the highlighted Agents row visible and clear of the footer", async ({
  page,
}) => {
  await page.route("**/v1/runtime-templates", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items }),
    }),
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/canvas");
  await expect(page.locator(".canvas-route-shell")).toBeVisible();

  // ⌘A opens straight into the Agents scope; wait for specialists to load.
  await page.keyboard.press("Meta+a");
  await expect(page.getByRole("combobox")).toBeVisible();
  await expect(page.getByText("specialist-0")).toBeVisible();

  // Arrow well past the fold.
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press("ArrowDown");
  }

  const active = page.locator(".launcher__row[data-highlighted]").first();
  await expect(active).toBeVisible();

  const activeBox = await active.boundingBox();
  const listBox = await page.locator(".launcher__content").boundingBox();
  const footerBox = await page.locator(".launcher__footer").boundingBox();
  if (!activeBox || !listBox || !footerBox) throw new Error("expected bounding boxes");

  // The highlighted row is fully inside the scroll viewport (not clipped at top
  // or bottom by the scroll) ...
  expect(activeBox.y).toBeGreaterThanOrEqual(listBox.y - 1);
  expect(activeBox.y + activeBox.height).toBeLessThanOrEqual(listBox.y + listBox.height + 1);
  // ... and never sits under the fixed footer.
  expect(activeBox.y + activeBox.height).toBeLessThanOrEqual(footerBox.y + 1);
});
