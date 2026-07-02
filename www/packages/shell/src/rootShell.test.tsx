import { act, screen } from "@testing-library/react";
import { clearThemeTokens, useThemeStore } from "@tm/canvas";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "@tm/core/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RootShell } from "./rootShell";

vi.mock("@tm/canvas/ambient/createAmbientBackground");

// The canvas route loads through React.lazy; under full-suite load the chunk can
// outlive findBy's 1s default, so wait generously for the canvas shell to paint.
const findCanvasShell = () => screen.findByRole("main", {}, { timeout: 10_000 });

// Theme cycling is now a ⌘K command-center entry (the always-visible bar is
// gone), which calls the store's cycleTheme — drive that directly.
const cycleTheme = () => act(() => useThemeStore.getState().cycleTheme());

function metaPayload() {
  return {
    channel: "stable",
    channel_badge: null,
    channel_label: "Stable",
    cwd: "/tmp/project",
    harnesses: [],
    run_id: null,
    workspace_id: "project/hash",
  };
}

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

    expect(useThemeStore.getState().theme?.id).toBe("open-water");
    expect(document.documentElement.style.getPropertyValue("--color-accent")).not.toBe("");
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe(
      "blur(18px) saturate(120%)",
    );
  });

  it("leaves inspector accent tokens at stylesheet defaults when a canvas theme is persisted", async () => {
    window.history.pushState({}, "", "/");
    installMockTransport(() => jsonResponse(metaPayload()));
    cycleTheme();

    renderWithQuery(<RootShell />);

    expect(await screen.findByText("Waiting for exchanges")).toBeInTheDocument();
    expect(useThemeStore.getState().theme?.id).toBe("open-water");
    expect(document.documentElement.style.getPropertyValue("--color-accent")).toBe("");
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe("");
  });

  it("clears the tokens again when the cycle returns to unthemed", async () => {
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<RootShell />);
    await findCanvasShell();

    cycleTheme(); // open-water
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe(
      "blur(18px) saturate(120%)",
    );

    cycleTheme(); // littleorgans
    cycleTheme(); // back to unthemed
    expect(useThemeStore.getState().theme).toBeNull();
    expect(document.documentElement.style.getPropertyValue("--pane-blur")).toBe("");
  });
});
