import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearThemeTokens } from "./hooks/useThemeTokens";
import { RootShell } from "./rootShell";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "./session-canvas/testUtils";
import { useThemeStore } from "./stores/themeStore";

vi.mock("./ambient/createAmbientBackground");

// The canvas route loads through React.lazy; under full-suite load the chunk can
// outlive findBy's 1s default, so wait generously for the canvas shell to paint.
const findCanvasShell = () => screen.findByRole("main", {}, { timeout: 10_000 });

// Theme cycling is now a ⌘K command-center entry (the always-visible bar is
// gone), which calls the store's cycleTheme — drive that directly.
const cycleTheme = () => act(() => useThemeStore.getState().cycleTheme());

describe("RootShell", () => {
  beforeEach(() => {
    // Tests drive the cycle from the unthemed state; the shipped default is
    // open-water (covered by themeStore tests).
    useThemeStore.setState({ theme: null });
  });

  afterEach(() => {
    restoreTransport();
    useThemeStore.setState({ theme: null });
    clearThemeTokens();
    window.history.pushState({}, "", "/");
  });

  it("applies theme tokens on the canvas route", async () => {
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<RootShell />);
    await findCanvasShell();

    cycleTheme();

    expect(useThemeStore.getState().theme?.id).toBe("littleorgans");
    expect(document.documentElement.style.getPropertyValue("--color-accent")).not.toBe("");
    expect(document.documentElement.style.getPropertyValue("--pane-surface-alpha")).toBe("0.74");
  });

  it("clears the tokens again when the theme is cleared", async () => {
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<RootShell />);
    await findCanvasShell();

    cycleTheme(); // littleorgans
    cycleTheme(); // open-water
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe(
      "blur(18px) saturate(120%)",
    );

    act(() => useThemeStore.getState().clearTheme());
    expect(useThemeStore.getState().theme).toBeNull();
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe("");
  });
});
