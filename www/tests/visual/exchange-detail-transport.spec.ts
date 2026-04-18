import { expect, test } from "@playwright/test";
import {
  mockCodexTransportDiagnosticId,
  mockCodexTransportSuccessId,
  setupVisualTest,
} from "./fixtures";

test.describe("exchange detail transport — codex websocket states", () => {
  test("captured websocket transport tab", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockCodexTransportSuccessId,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: /gpt-5-codex/i }).waitFor();

    const transportTab = page
      .locator("main")
      .getByRole("button", { name: /^transport(?:\s+\d+\s+frames?)?$/i });
    await transportTab.click();
    await page.getByText("/backend-api/codex/responses?client=cli").waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-transport-codex.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 900 },
    });
  });

  test("transport diagnostics panel", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupVisualTest(page, {
      armed: false,
      paused: false,
      selectedExchangeId: mockCodexTransportDiagnosticId,
    });
    await page.goto("/");
    await page.getByRole("heading", { name: /transport-handshake/i }).waitFor();

    const transportTab = page
      .locator("main")
      .getByRole("button", { name: /^transport(?:\s+\d+\s+frames?)?$/i });
    await transportTab.click();
    await page.getByText("Proxy trust failed before the Codex websocket upgraded.").waitFor();
    await page.getByText("CODEX_CA_CERTIFICATE").waitFor();

    await expect(page).toHaveScreenshot("exchange-detail-transport-diagnostics.png", {
      animations: "disabled",
      clip: { x: 0, y: 0, width: 1440, height: 900 },
    });
  });
});
