import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaneId } from "../../engine";
import type { HarnessName } from "../../types";
import { resetCanvasStoreForTests, useCanvasStore } from "../model/canvasStore";
import type { CanvasLaunchContext } from "../route";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "../testUtils";
import { CanvasSurface } from "./CanvasSurface";

vi.mock("../../ambient/createAmbientBackground");

const launch = {
  owner: "local",
  workspaceHash: "hash-1",
  harness: null,
  runId: null,
} satisfies CanvasLaunchContext;

describe("CanvasSurface", () => {
  afterEach(() => {
    resetCanvasStoreForTests();
    restoreTransport();
    vi.restoreAllMocks();
  });

  it("re-homes native captured-run spawn into the ⌘K command center", async () => {
    resetCanvasStoreForTests(launch);
    installMockTransport(() => jsonResponse({ items: [] }));
    const addCapturedRun = vi.fn(
      (provider: HarnessName, _runtimeTemplate?: string): PaneId => `captured:${provider}`,
    );
    useCanvasStore.setState({ addCapturedRun });

    renderWithQuery(
      <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />,
    );

    // Zero-chrome: the always-visible command bar is gone.
    expect(screen.queryByRole("toolbar", { name: "Canvas commands" })).not.toBeInTheDocument();

    // ⌘A jumps into Agents; both native harnesses are always present.
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();

    // ↵ on the auto-highlighted first native spawns it through the canvas handler.
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    await waitFor(() => expect(addCapturedRun).toHaveBeenCalledWith("claude", undefined));
  });

  it("closes the command center on Escape from a sub-scope", async () => {
    resetCanvasStoreForTests(launch);
    installMockTransport(() => jsonResponse({ items: [] }));

    renderWithQuery(
      <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />,
    );

    // Open into the Agents scope, then Escape must close the WHOLE palette — the
    // root capture handler beats Ark, which would otherwise only close its listbox.
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    const input = await screen.findByRole("combobox");

    fireEvent.keyDown(input, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("combobox")).not.toBeInTheDocument());
  });
});
