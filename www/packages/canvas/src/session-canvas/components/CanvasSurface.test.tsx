import { fireEvent, screen, waitFor } from "@testing-library/react";
import { resolveKeybindingPlatform } from "@tm/core/keybindings";
import type { HarnessName } from "@tm/core/types/capabilities";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaneId } from "../../engine";
import { KeybindingEngineProvider } from "../../keybindings/engine";
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
  spaceId: null,
  worktreeId: null,
  canvasId: null,
  harness: null,
  runId: null,
} satisfies CanvasLaunchContext;

const testPlatform = resolveKeybindingPlatform({
  navigator: { userAgent: "Macintosh" } as Navigator,
});

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
      (provider: HarnessName, _runtimeTemplate?: string, _worktreeId?: string): PaneId =>
        `captured:${provider}`,
    );
    useCanvasStore.setState({ addCapturedRun });

    renderWithQuery(
      <KeybindingEngineProvider platform={testPlatform}>
        <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />
      </KeybindingEngineProvider>,
    );

    // Zero-chrome: the always-visible command bar is gone.
    expect(screen.queryByRole("toolbar", { name: "Canvas commands" })).not.toBeInTheDocument();

    // ⌘A jumps into Agents; both native harnesses are always present.
    fireEvent.keyDown(window, { key: "a", code: "KeyA", metaKey: true });
    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();

    // ↵ on the auto-highlighted first native spawns it through the canvas handler.
    // A root/Agents-scope spawn carries no per-spawn worktree, so worktreeId is undefined.
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    await waitFor(() =>
      expect(addCapturedRun).toHaveBeenCalledWith("claude", undefined, undefined),
    );
  });

  it("closes the command center on Escape from a sub-scope", async () => {
    resetCanvasStoreForTests(launch);
    installMockTransport(() => jsonResponse({ items: [] }));

    renderWithQuery(
      <KeybindingEngineProvider platform={testPlatform}>
        <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />
      </KeybindingEngineProvider>,
    );

    // Open into the Agents scope, then Escape must close the WHOLE palette — the
    // root capture handler beats Ark, which would otherwise only close its listbox.
    fireEvent.keyDown(window, { key: "a", code: "KeyA", metaKey: true });
    const input = await screen.findByRole("combobox");

    fireEvent.keyDown(input, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("combobox")).not.toBeInTheDocument());
  });

  it("surfaces a captured-run spawn failure as a non-fatal error instead of crashing the surface", async () => {
    resetCanvasStoreForTests(launch);
    installMockTransport(() => jsonResponse({ items: [] }));
    // Mirrors canvasStore.addCapturedRun's throw on a rootless canvas
    // (defaultWorktreeId === null). The spawn handler must CATCH it so this event
    // dispatch does not bubble an uncaught error out of the React handler (UI crash).
    const addCapturedRun = vi.fn((): PaneId => {
      throw new Error("Cannot spawn a captured run without a rooted worktree");
    });
    useCanvasStore.setState({ addCapturedRun });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderWithQuery(
      <KeybindingEngineProvider platform={testPlatform}>
        <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />
      </KeybindingEngineProvider>,
    );

    fireEvent.keyDown(window, { key: "a", code: "KeyA", metaKey: true });
    // Without the handler's try/catch this fireEvent throws (uncaught handler error).
    fireEvent.keyDown(await screen.findByRole("combobox"), { key: "Enter" });

    await waitFor(() => expect(addCapturedRun).toHaveBeenCalled());
    expect(errorSpy).toHaveBeenCalled();
  });
});
