import type { Page } from "@playwright/test";

export async function pressMod(page: Page, key: string) {
  const isMac = await page.evaluate(() => /mac|darwin/i.test(navigator.userAgent));
  await page.keyboard.press(`${isMac ? "Meta" : "Control"}+${key}`);
}
