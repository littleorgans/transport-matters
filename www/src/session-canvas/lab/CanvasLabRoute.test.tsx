import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CliCapability, CliName } from "../../types";
import { CanvasLabRoute } from "./CanvasLabRoute";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { resetCapabilitiesStoreForTests, useCapabilitiesStore } from "./capabilitiesStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";

vi.mock("../../api", () => ({
  createCapturedRun: vi.fn(),
  deleteRun: vi.fn(),
}));

// The lab gates its captured-run spawn buttons on managed-CLI availability. Seeding
// the capabilities store to "ready" makes CanvasLabRoute's mount-time probe a no-op,
// so these tests drive button visibility directly off install state with no network.

function capability(installed: boolean): CliCapability {
  return {
    installed,
    path: installed ? "/usr/local/bin/cli" : null,
    version: installed ? "1.0.0" : null,
  };
}

function seedCapabilities(installed: Record<CliName, boolean>): void {
  useCapabilitiesStore.setState({
    status: "ready",
    clis: { claude: capability(installed.claude), codex: capability(installed.codex) },
  });
}

describe("CanvasLabRoute captured-run spawn buttons", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    resetCapabilitiesStoreForTests();
    resetCapturedRunStoreForTests();
  });

  afterEach(() => {
    resetCanvasLabStoreForTests();
    resetCapabilitiesStoreForTests();
    resetCapturedRunStoreForTests();
  });

  it("shows both spawn buttons when both CLIs are installed", () => {
    seedCapabilities({ claude: true, codex: true });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("hides the codex button when codex is not installed", () => {
    seedCapabilities({ claude: true, codex: false });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Spawn Codex" })).not.toBeInTheDocument();
  });

  it("hides the claude button when claude is not installed", () => {
    seedCapabilities({ claude: false, codex: true });
    render(<CanvasLabRoute />);
    expect(screen.queryByRole("button", { name: "Spawn Claude" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("hides both spawn buttons when neither CLI is installed", () => {
    seedCapabilities({ claude: false, codex: false });
    render(<CanvasLabRoute />);
    expect(screen.queryByRole("button", { name: "Spawn Claude" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Spawn Codex" })).not.toBeInTheDocument();
  });

  it("keeps both spawn buttons when the capability probe is unreachable (dev server, no backend)", () => {
    // Fail-open: a failed/unknown probe must not hide the controls. Seeding "error"
    // makes the mount-time probe a no-op, reproducing a dev server with no backend.
    useCapabilitiesStore.setState({ status: "error", clis: null });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("re-adds a captured-run pane on mount for each persisted run (reload re-attach)", () => {
    // A browser reload drops the in-memory lab store but keeps each pane's run. The lab
    // reconciles on mount so every captured pane reappears at its key and re-attaches by
    // id instead of leaving the headless run orphaned.
    useCapturedRunStore.setState({
      runs: { "claude:k1": { provider: "claude", runId: "run-1" } },
    });
    seedCapabilities({ claude: true, codex: true });

    render(<CanvasLabRoute />);

    expect(useCanvasLabStore.getState().contentRefs["claude:k1"]).toEqual({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k1",
    });
  });

  it("docks a persisted minimized run on mount instead of reopening it (reload-persist)", () => {
    // A run minimized before a browser reload must come back DOCKED, not as an active pane. The kept
    // runId lets a later restore re-attach by id (no re-spawn); on mount it simply parks in the dock.
    useCapturedRunStore.setState({
      runs: { "claude:k1": { provider: "claude", runId: "run-1", minimized: true } },
    });
    seedCapabilities({ claude: true, codex: true });

    render(<CanvasLabRoute />);

    // Not reopened as an active pane...
    expect(useCanvasLabStore.getState().contentRefs["claude:k1"]).toBeUndefined();
    // ...parked in the dock instead, so the operator restores it deliberately.
    expect(useCanvasLabStore.getState().docked.map((entry) => entry.paneId)).toEqual(["claude:k1"]);
    expect(screen.getByRole("button", { name: "Minimized panes, 1" })).toBeInTheDocument();
  });

  it("keeps the dock visible when the lab top bar is TAB-hidden", () => {
    seedCapabilities({ claude: true, codex: true });
    render(<CanvasLabRoute />);
    // Park a pane in the dock (its only source) directly, skipping the close-delay timer.
    act(() => {
      useCanvasLabStore.setState({
        docked: [{ paneId: "lab-1", ref: { kind: "terminal", owner: "local" } }],
      });
    });

    expect(screen.getByRole("toolbar", { name: "Canvas lab controls" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimized panes, 1" })).toBeInTheDocument();

    // TAB hides the command bar; the dock lives in the canvas viewport overlay (not the bar), so it
    // persists — the operator can still restore a minimized pane in cockpit mode.
    act(() => {
      fireEvent.keyDown(window, { key: "Tab" });
    });

    expect(screen.queryByRole("toolbar", { name: "Canvas lab controls" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimized panes, 1" })).toBeInTheDocument();
  });
});
