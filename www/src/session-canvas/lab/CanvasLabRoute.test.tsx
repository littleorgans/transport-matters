import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import type { HarnessCapability, HarnessName } from "../../types";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "../model/capturedRunStore";
import { CanvasLabRoute } from "./CanvasLabRoute";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { CANVAS_LAB_STORAGE_VERSION } from "./canvasLabStore.persistence";
import { resetCapabilitiesStoreForTests, useCapabilitiesStore } from "./capabilitiesStore";

vi.mock("../../api", () => ({
  createCapturedRun: vi.fn(),
  terminateRun: vi.fn(),
}));
vi.mock("../../ambient/createAmbientBackground");

// The lab gates its captured-run spawn buttons on managed harness availability. Seeding
// the capabilities store to "ready" makes CanvasLabRoute's mount-time probe a no-op,
// so these tests drive button visibility directly off install state with no network.

function capability(installed: boolean): HarnessCapability {
  return {
    installed,
    path: installed ? "/usr/local/bin/harness" : null,
    version: installed ? "1.0.0" : null,
  };
}

function seedCapabilities(installed: Record<HarnessName, boolean>): void {
  useCapabilitiesStore.setState({
    status: "ready",
    harnesses: { claude: capability(installed.claude), codex: capability(installed.codex) },
  });
}

const SEED_RECT = { x: 48, y: 48, width: 360, height: 280 } as const;

function capturedRef(runKey: string, label: string) {
  return { kind: "captured-run", owner: "local", provider: "claude", runKey, label } as const;
}

// Seed both persisted payloads for a reload: the lab store's own record set plus the captured-run
// bindings it composes with. beforeEach has already reset the in-memory stores; callers rehydrate after.
function seedPersistedLab(
  labState: Record<string, unknown>,
  runs: Record<string, { provider: HarnessName; runId: string; minimized?: boolean }>,
): void {
  localStorage.setItem(
    FRONTEND_STORAGE_KEYS.canvasLabStore,
    JSON.stringify({ version: CANVAS_LAB_STORAGE_VERSION, state: labState }),
  );
  localStorage.setItem(
    FRONTEND_STORAGE_KEYS.capturedRunStore,
    JSON.stringify({ version: 4, state: { runs, oscColorReplies: true } }),
  );
}

function resetLabStores(): void {
  resetCanvasLabStoreForTests();
  resetCapabilitiesStoreForTests();
  resetCapturedRunStoreForTests();
}

describe("CanvasLabRoute captured-run spawn buttons", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLabStores();
  });

  afterEach(resetLabStores);

  it("shows both spawn buttons when both harnesses are installed", () => {
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

  it("hides both spawn buttons when neither harness is installed", () => {
    seedCapabilities({ claude: false, codex: false });
    render(<CanvasLabRoute />);
    expect(screen.queryByRole("button", { name: "Spawn Claude" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Spawn Codex" })).not.toBeInTheDocument();
  });

  it("keeps both spawn buttons when the capability probe is unreachable (dev server, no backend)", () => {
    // Fail-open: a failed/unknown probe must not hide the controls. Seeding "error"
    // makes the mount-time probe a no-op, reproducing a dev server with no backend.
    useCapabilitiesStore.setState({ status: "error", harnesses: null });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("restores a persisted open captured-run pane onto the canvas after a reload", async () => {
    // After S3 a browser reload rehydrates the lab store's own record set: a previously-open captured
    // pane comes back ON THE CANVAS at its key carrying its label, and re-attaches to its kept runId
    // (capturedRunStore) instead of re-spawning; no mount-time reconcile in the route.
    seedCapabilities({ claude: true, codex: true });
    seedPersistedLab(
      {
        contentRefs: {
          "claude:k1": capturedRef("claude:k1", "Claude-1"),
        },
        paneRects: { "claude:k1": SEED_RECT },
        docked: [],
        paneCounters: { Claude: 1 },
        nextPaneIndex: 0,
      },
      { "claude:k1": { provider: "claude", runId: "run-1" } },
    );
    await useCapturedRunStore.persist.rehydrate();
    await useCanvasLabStore.persist.rehydrate();

    render(<CanvasLabRoute />);

    expect(useCanvasLabStore.getState().contentRefs["claude:k1"]).toMatchObject({
      runKey: "claude:k1",
      label: "Claude-1",
    });
    expect(useCanvasLabStore.getState().layout.nodes["claude:k1"]).toBeDefined();
    // The kept runId means the viewer re-attaches by id; no new run is POSTed.
    expect(useCapturedRunStore.getState().runs["claude:k1"]).toEqual({
      provider: "claude",
      runId: "run-1",
    });
  });

  it("restores persisted docked panes of every kind into the dock after a reload", async () => {
    // The all-kind dock round-trip: a docked terminal AND a docked regular pane (plus a captured one)
    // come back IN THE DOCK after a reload, not on the canvas and not lost. The dock count reflects all.
    seedCapabilities({ claude: true, codex: true });
    seedPersistedLab(
      {
        contentRefs: {},
        paneRects: {},
        docked: [
          { paneId: "lab-1", ref: { kind: "terminal", owner: "local", label: "Terminal-1" } },
          { paneId: "lab-2", ref: null },
          { paneId: "claude:k1", ref: capturedRef("claude:k1", "Claude-1") },
        ],
        paneCounters: { Terminal: 1, Claude: 1 },
        nextPaneIndex: 2,
      },
      { "claude:k1": { provider: "claude", runId: "run-1", minimized: true } },
    );
    await useCapturedRunStore.persist.rehydrate();
    await useCanvasLabStore.persist.rehydrate();

    render(<CanvasLabRoute />);

    // None reopened on the canvas; all three parked in the dock.
    expect(useCanvasLabStore.getState().layout.nodes).toEqual({});
    expect(
      useCanvasLabStore
        .getState()
        .docked.map((entry) => entry.paneId)
        .sort(),
    ).toEqual(["claude:k1", "lab-1", "lab-2"]);
    expect(screen.getByRole("button", { name: "Minimized panes, 3" })).toBeInTheDocument();
  });

  it("resets a stale cache with legacy pane refs before mounting the route", async () => {
    seedCapabilities({ claude: true, codex: true });
    seedPersistedLab(
      {
        contentRefs: {
          "lab-1": { kind: "session", owner: "local", sessionId: "legacy-session" },
        },
        paneRects: { "lab-1": SEED_RECT },
        docked: [],
        activeStrategyId: "grid-fit",
        params: {},
        fitToContent: true,
        expandedPaneId: null,
        paneCounters: {},
        nextPaneIndex: 1,
      },
      {},
    );

    await useCanvasLabStore.persist.rehydrate();

    render(<CanvasLabRoute />);

    expect(screen.getByRole("toolbar", { name: "Canvas lab controls" })).toBeInTheDocument();
    expect(useCanvasLabStore.getState().contentRefs).toEqual({});
    expect(useCanvasLabStore.getState().layout.nodes).toEqual({});
    expect(useCanvasLabStore.getState().docked).toEqual([]);
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
    // persists, so the operator can still restore a minimized pane in cockpit mode.
    act(() => {
      fireEvent.keyDown(window, { key: "Tab" });
    });

    expect(screen.queryByRole("toolbar", { name: "Canvas lab controls" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimized panes, 1" })).toBeInTheDocument();
  });
});

describe("CanvasLabRoute text shadow", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLabStores();
  });

  afterEach(resetLabStores);

  it("toggles the shell's CSS hook on and off", () => {
    seedCapabilities({ claude: true, codex: true });
    render(<CanvasLabRoute />);
    const shell = screen.getByRole("main");
    // The control lives in the secondary command-bar group behind the toggle.
    fireEvent.click(screen.getByRole("button", { name: "Layout" }));
    const checkbox = screen.getByRole("checkbox", { name: "Text shadow" });
    expect(shell).not.toHaveAttribute("data-text-shadow");

    fireEvent.click(checkbox);
    expect(shell).toHaveAttribute("data-text-shadow");

    fireEvent.click(checkbox);
    expect(shell).not.toHaveAttribute("data-text-shadow");
  });

  it("rehydrates a persisted choice and sanitizes junk values to off", async () => {
    const labExtras = { contentRefs: {}, paneRects: {}, docked: [], paneCounters: {} };
    seedPersistedLab({ ...labExtras, nextPaneIndex: 0, textShadow: true }, {});
    await useCanvasLabStore.persist.rehydrate();
    expect(useCanvasLabStore.getState().textShadow).toBe(true);

    seedPersistedLab({ ...labExtras, nextPaneIndex: 0, textShadow: "scrim" }, {});
    await useCanvasLabStore.persist.rehydrate();
    expect(useCanvasLabStore.getState().textShadow).toBe(false);
  });
});

describe("CanvasLabRoute harness color replies", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLabStores();
  });

  afterEach(resetLabStores);

  it("defaults on and unchecking writes the store", () => {
    seedCapabilities({ claude: true, codex: true });
    render(<CanvasLabRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Layout" }));
    const checkbox = screen.getByRole("checkbox", { name: "Harness color replies" });
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    expect(useCapturedRunStore.getState().oscColorReplies).toBe(false);
  });

  it("rehydrates the core field instead of lab-local state", async () => {
    seedCapabilities({ claude: true, codex: true });
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.capturedRunStore,
      JSON.stringify({ version: 4, state: { runs: {}, oscColorReplies: false } }),
    );

    await useCapturedRunStore.persist.rehydrate();
    render(<CanvasLabRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Layout" }));

    expect(screen.getByRole("checkbox", { name: "Harness color replies" })).not.toBeChecked();
  });
});
