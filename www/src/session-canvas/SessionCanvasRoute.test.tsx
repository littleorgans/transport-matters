import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetCanvasStoreForTests, useCanvasStore } from "./model/canvasStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./model/capturedRunStore";
import { SessionCanvasRoute } from "./SessionCanvasRoute";
import {
  installMockTransport,
  jsonResponse,
  makeSessionEvent,
  makeSessionSummary,
  renderWithQuery,
  restoreTransport,
} from "./testUtils";

vi.mock("../ambient/createAmbientBackground");

const { capturedRunPaneRender } = vi.hoisted(() => ({
  capturedRunPaneRender: vi.fn(),
}));

vi.mock("./viewers/terminal/CapturedRunPane", () => ({
  CapturedRunPane: ({ runKey }: { runKey: string }) => {
    capturedRunPaneRender(runKey);
    return <div data-testid="captured-run-pane">{runKey}</div>;
  },
}));

class MockEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();
}

function capturedRunRef(runKey: string) {
  return { kind: "captured-run", owner: "local", provider: "claude", runKey } as const;
}

function rememberCapturedRun(runKey: string, runId: string): void {
  useCapturedRunStore.setState((state) => ({
    runs: { ...state.runs, [runKey]: { provider: "claude", runId } },
  }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

describe("SessionCanvasRoute", () => {
  afterEach(() => {
    resetCapturedRunStoreForTests();
    capturedRunPaneRender.mockClear();
    restoreTransport();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the picker immediately", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));

    renderWithQuery(<SessionCanvasRoute />);

    // Zero-chrome: the always-visible command bar is gone (replaced by ⌘K).
    expect(screen.queryByRole("toolbar", { name: "Canvas commands" })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("No sessions found for this canvas.")).toBeInTheDocument(),
    );
  });

  it("withholds captured run content during startup reconciliation while the picker renders", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:stale", "run-stale");
    useCanvasStore.getState().spawnPane(capturedRunRef("claude:stale"));
    window.history.pushState({}, "", "/canvas");
    const runs = deferred<Response>();
    installMockTransport((path) =>
      path === "/v1/runs" ? runs.promise : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    expect(await screen.findByTestId("captured-run-reconciliation-placeholder")).toHaveTextContent(
      "Checking captured run state…",
    );
    expect(screen.queryByTestId("captured-run-pane")).not.toBeInTheDocument();
    expect(capturedRunPaneRender).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByText("No sessions found for this canvas.")).toBeInTheDocument(),
    );
  });

  it("keeps a remembered captured run when the live run list still contains it", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:live", "run-live");
    useCanvasStore.getState().spawnPane(capturedRunRef("claude:live"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs"
        ? jsonResponse({
            items: [
              {
                runId: "run-live",
                workspaceId: "workspace",
                sessionId: "session",
                harness: "claude",
                state: "RUNNING",
                createdAt: "2026-06-20T12:00:00Z",
              },
            ],
            nextCursor: null,
          })
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:live"));
    expect(useCapturedRunStore.getState().runs["claude:live"]?.runId).toBe("run-live");
    expect(useCanvasStore.getState().panes["claude:live"]).toBeDefined();
  });

  it("prunes absent start-candidate run ids from the run store and open or docked panes", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:open", "run-open");
    rememberCapturedRun("claude:docked", "run-docked");
    useCanvasStore.getState().spawnPane(capturedRunRef("claude:open"));
    useCanvasStore.getState().dockPane(capturedRunRef("claude:docked"));
    window.history.pushState({}, "", "/canvas");
    const paths: string[] = [];
    installMockTransport((path) => {
      paths.push(path);
      return jsonResponse({ items: [], nextCursor: null });
    });

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(useCapturedRunStore.getState().runs["claude:open"]).toBeUndefined();
      expect(useCapturedRunStore.getState().runs["claude:docked"]).toBeUndefined();
    });
    expect(useCanvasStore.getState().panes["claude:open"]).toBeUndefined();
    expect(useCanvasStore.getState().docked).toHaveLength(0);
    expect(paths.filter((path) => path === "/v1/runs")).toHaveLength(1);
    expect(paths.some((path) => path.includes("/terminate"))).toBe(false);
    expect(capturedRunPaneRender).not.toHaveBeenCalled();
  });

  it("preserves a captured run persisted during the listRuns round trip", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:old", "run-old");
    useCanvasStore.getState().spawnPane(capturedRunRef("claude:old"));
    window.history.pushState({}, "", "/canvas");
    const runs = deferred<Response>();
    installMockTransport((path) =>
      path === "/v1/runs" ? runs.promise : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);
    await screen.findByTestId("captured-run-reconciliation-placeholder");

    act(() => {
      rememberCapturedRun("claude:new", "run-new");
      useCanvasStore.getState().spawnPane(capturedRunRef("claude:new"));
    });
    await act(async () => {
      runs.resolve(jsonResponse({ items: [], nextCursor: null }));
      await runs.promise;
    });

    await waitFor(() => {
      expect(useCapturedRunStore.getState().runs["claude:old"]).toBeUndefined();
      expect(useCapturedRunStore.getState().runs["claude:new"]?.runId).toBe("run-new");
    });
    expect(useCanvasStore.getState().panes["claude:old"]).toBeUndefined();
    expect(useCanvasStore.getState().panes["claude:new"]).toBeDefined();
    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:new"));
  });

  it("keeps local captured run state and releases the gate when listRuns fails", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:kept", "run-kept");
    useCanvasStore.getState().spawnPane(capturedRunRef("claude:kept"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs"
        ? jsonResponse({ detail: "backend unavailable" }, 503)
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:kept"));
    expect(useCapturedRunStore.getState().runs["claude:kept"]?.runId).toBe("run-kept");
    expect(useCanvasStore.getState().panes["claude:kept"]).toBeDefined();
  });

  it("auto resolves the launched run into the transcript seam", async () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ sessionId: "session-live" });
    window.history.pushState(
      {},
      "",
      "/canvas?owner=local&workspace_hash=hash-1&harness=claude&run_id=run-live",
    );
    vi.stubGlobal("EventSource", MockEventSource);
    installMockTransport((path) =>
      path.includes("/events?")
        ? jsonResponse({
            events: [makeSessionEvent()],
            nextFromSeq: null,
          })
        : jsonResponse({ items: [session], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(screen.getByText("hello transcript")).toBeInTheDocument();
    });
  });

  it("feeds surface resize bounds into canvas planning", async () => {
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));
    let width = 900;
    let height = 700;
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(() => width);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(() => height);
    // dnd-kit observes droppable panes with its own ResizeObservers, so the
    // surface bounds observer is found by its observed element, not by count.
    const observers: Array<{ callback: ResizeObserverCallback; targets: Element[] }> = [];
    class MockResizeObserver {
      targets: Element[] = [];
      observe = vi.fn((target: Element) => {
        this.targets.push(target);
      });
      unobserve = vi.fn();
      disconnect = vi.fn();

      constructor(readonly callback: ResizeObserverCallback) {
        observers.push(this);
      }
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);

    renderWithQuery(<SessionCanvasRoute />);

    const surfaceObserver = () =>
      observers.find((observer) =>
        observer.targets.some((target) => target.classList.contains("canvas-route-shell")),
      );
    await waitFor(() => expect(surfaceObserver()).toBeDefined());
    expect(useCanvasStore.getState().bounds).toEqual({ width: 900, height: 700 });

    act(() => {
      width = 640;
      height = 480;
      const observer = surfaceObserver();
      observer?.callback([], observer as unknown as ResizeObserver);
    });

    expect(useCanvasStore.getState().bounds).toEqual({ width: 640, height: 480 });
  });

  it("renders pane affordance controls and dispatches header double-click gestures", () => {
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));

    renderWithQuery(<SessionCanvasRoute />);
    act(() => {
      useCanvasStore
        .getState()
        .spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc", title: "Project agent" }));
    });

    expect(screen.getByRole("button", { name: "Frame Project agent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand Project agent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Minimize Project agent" })).toBeInTheDocument();

    const header = screen.getByRole("heading", { name: "Project agent" }).closest("header");
    if (!header) throw new Error("expected Project agent pane header");

    fireEvent.doubleClick(header);
    expect(useCanvasStore.getState().framing.paneId).toBe("transcript:abc");

    fireEvent.doubleClick(header, { shiftKey: true });
    expect(useCanvasStore.getState().expandedPaneId).toBe("transcript:abc");
  });

  it("renders the pane dock and restores a minimized pane", () => {
    vi.useFakeTimers();
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));

    renderWithQuery(<SessionCanvasRoute />);
    act(() => {
      useCanvasStore
        .getState()
        .spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc", title: "Project agent" }));
    });

    act(() => {
      useCanvasStore.getState().minimizePane("transcript:abc");
      vi.runAllTimers();
    });

    const chip = screen.getByRole("button", { name: "Minimized panes, 1" });
    expect(chip).toBeInTheDocument();

    fireEvent.click(chip);
    fireEvent.click(screen.getByRole("menuitem", { name: "Project agent" }));

    expect(useCanvasStore.getState().docked).toEqual([]);
    expect(screen.getByRole("heading", { name: "Project agent" })).toBeInTheDocument();
  });
});
