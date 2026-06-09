import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RunView } from "../../api";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";
import { DirectorPanel } from "./DirectorPanel";

// The director surface only reads /api/runs and stops runs; attach reuses the real
// captured-run/lab stores (no network), so the api boundary is the only thing mocked.
const { listRunsMock, deleteRunMock, createCapturedRunMock } = vi.hoisted(() => ({
  listRunsMock: vi.fn(),
  deleteRunMock: vi.fn(),
  createCapturedRunMock: vi.fn(),
}));
vi.mock("../../api", () => ({
  listRuns: listRunsMock,
  deleteRun: deleteRunMock,
  createCapturedRun: createCapturedRunMock,
}));

function runView(runId: string, cli: RunView["cli"], over: Partial<RunView> = {}): RunView {
  return {
    runId,
    cli,
    cwd: "/work/proj",
    storageDir: "/store",
    proxyPort: 4010,
    state: "running",
    viewerCount: 0,
    createdAt: "2026-06-09T00:00:00+00:00",
    startedAt: "2026-06-09T00:00:01+00:00",
    updatedAt: "2026-06-09T00:00:02+00:00",
    scrollbackBytes: 0,
    scrollbackLimitBytes: 1048576,
    ...over,
  };
}

function capturedPaneIds(): string[] {
  return Object.entries(useCanvasLabStore.getState().contentRefs)
    .filter(([, ref]) => ref.kind === "captured-run")
    .map(([paneId]) => paneId);
}

describe("DirectorPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    resetCapturedRunStoreForTests();
    listRunsMock.mockReset();
    deleteRunMock.mockReset();
    createCapturedRunMock.mockReset();
  });

  it("lists live runs from GET /api/runs on mount", async () => {
    listRunsMock.mockResolvedValue([
      runView("run-1", "claude", { cwd: "/work/alpha", state: "running", viewerCount: 2 }),
    ]);

    render(<DirectorPanel />);

    expect(await screen.findByText("/work/alpha")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("2 viewers")).toBeInTheDocument();
    expect(listRunsMock).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state when there are no live runs", async () => {
    listRunsMock.mockResolvedValue([]);

    render(<DirectorPanel />);

    expect(await screen.findByText("No live runs.")).toBeInTheDocument();
  });

  it("re-fetches the roster on manual refresh", async () => {
    listRunsMock.mockResolvedValueOnce([]).mockResolvedValueOnce([runView("run-1", "codex")]);

    render(<DirectorPanel />);
    expect(await screen.findByText("No live runs.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(listRunsMock).toHaveBeenCalledTimes(2);
  });

  it("attaches to an existing run id without spawning a second run", async () => {
    listRunsMock.mockResolvedValue([runView("run-1", "claude")]);

    render(<DirectorPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Attach" }));

    // A pane opened bound to the existing run id (adopted, not spawned).
    const ids = capturedPaneIds();
    expect(ids).toHaveLength(1);
    const runKey = ids[0];
    if (!runKey) throw new Error("expected a captured pane");
    expect(useCapturedRunStore.getState().runs[runKey]).toEqual({
      provider: "claude",
      runId: "run-1",
    });
    expect(createCapturedRunMock).not.toHaveBeenCalled();
  });

  it("stops a run from the list and refreshes it away", async () => {
    listRunsMock
      .mockResolvedValueOnce([runView("run-1", "claude", { cwd: "/work/alpha" })])
      .mockResolvedValueOnce([]);
    deleteRunMock.mockResolvedValue(undefined);

    render(<DirectorPanel />);
    const row = (await screen.findByText("/work/alpha")).closest("li");
    if (!row) throw new Error("expected a run row");

    fireEvent.click(within(row).getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(deleteRunMock).toHaveBeenCalledWith("run-1"));
    expect(await screen.findByText("No live runs.")).toBeInTheDocument();
  });

  it("hides terminal (exited/failed) runs from the live roster", async () => {
    listRunsMock.mockResolvedValue([
      runView("run-live", "claude", { cwd: "/live", state: "running" }),
      runView("run-dead", "claude", { cwd: "/dead", state: "exited" }),
      runView("run-bad", "codex", { cwd: "/bad", state: "failed" }),
    ]);

    render(<DirectorPanel />);

    expect(await screen.findByText("/live")).toBeInTheDocument();
    // A killed/exited run has left the roster, so the tray only shows live runs.
    expect(screen.queryByText("/dead")).not.toBeInTheDocument();
    expect(screen.queryByText("/bad")).not.toBeInTheDocument();
  });

  it("enables Attach only for running runs (backend attach requires RUNNING)", async () => {
    listRunsMock.mockResolvedValue([
      runView("run-1", "claude", { cwd: "/starting", state: "starting" }),
      runView("run-2", "codex", { cwd: "/running", state: "running" }),
    ]);

    render(<DirectorPanel />);
    const startingRow = (await screen.findByText("/starting")).closest("li");
    const runningRow = (await screen.findByText("/running")).closest("li");
    if (!startingRow || !runningRow) throw new Error("expected both run rows");

    expect(within(startingRow).getByRole("button", { name: "Attach" })).toBeDisabled();
    expect(within(runningRow).getByRole("button", { name: "Attach" })).toBeEnabled();
  });
});
