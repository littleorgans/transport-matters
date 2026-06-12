import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearThemeTokens } from "./hooks/useThemeTokens";
import { RootShell } from "./rootShell";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "./session-canvas/testUtils";
import { useThemeStore } from "./stores/themeStore";

// The canvas route loads through React.lazy; under full-suite load the chunk
// can outlive findByRole's 1s default, so wait generously for the first paint.
const findThemeButton = () =>
  screen.findByRole("button", { name: "Theme: none" }, { timeout: 10_000 });

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

    const button = await findThemeButton();
    fireEvent.click(button);

    expect(useThemeStore.getState().theme?.id).toBe("littleorgans");
    expect(document.documentElement.style.getPropertyValue("--color-accent")).not.toBe("");
    expect(document.documentElement.style.getPropertyValue("--pane-surface-alpha")).toBe("0.74");
  });

  it("clears the tokens again when the cycle returns to unthemed", async () => {
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<RootShell />);

    const button = await findThemeButton();
    fireEvent.click(button); // littleorgans
    fireEvent.click(button); // open-water
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe(
      "blur(18px) saturate(120%)",
    );

    fireEvent.click(button); // back to unthemed
    expect(useThemeStore.getState().theme).toBeNull();
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe("");
  });
});
