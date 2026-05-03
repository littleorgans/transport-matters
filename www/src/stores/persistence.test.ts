import { beforeEach, describe, expect, it } from "vitest";
import {
  createFrontendPersistStorage,
  dismissedPanelKey,
  FRONTEND_STORAGE_KEYS,
  hasDismissedPanel,
  markPanelDismissed,
} from "./persistence";

beforeEach(() => {
  localStorage.clear();
});

describe("frontend persistence", () => {
  it("keeps the current Manicure storage keys stable", () => {
    expect(FRONTEND_STORAGE_KEYS.uiStore).toBe("manicure-ui");
    expect(FRONTEND_STORAGE_KEYS.overlaysStore).toBe("manicure-overlays");
    expect(FRONTEND_STORAGE_KEYS.dismissedPanelPrefix).toBe("manicure.panel.dismissed.");
    expect(dismissedPanelKey("intro")).toBe("manicure.panel.dismissed.intro");
  });

  it("reads and writes dismissed panel state through localStorage", () => {
    expect(hasDismissedPanel("intro")).toBe(false);

    markPanelDismissed("intro");

    expect(hasDismissedPanel("intro")).toBe(true);
    expect(localStorage.getItem(dismissedPanelKey("intro"))).toBe("1");
  });

  it("treats unavailable storage as not dismissed", () => {
    const original = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("blocked");
      },
    });

    try {
      expect(hasDismissedPanel("intro")).toBe(false);
      expect(() => markPanelDismissed("intro")).not.toThrow();
      expect(createFrontendPersistStorage()).toBeUndefined();
    } finally {
      Object.defineProperty(globalThis, "localStorage", {
        configurable: true,
        value: original,
      });
    }
  });
});
