import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetCanvasStoreForTests, useCanvasStore } from "./model/canvasStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./model/capturedRunStore";
import { SessionCanvasRoute } from "./SessionCanvasRoute";
import {
  installMockTransport,
  jsonResponse,
  makeCapturedRunRef,
  makeSessionEvent,
  makeSessionSummary,
  rememberCapturedRun,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

function runLookupResponse(runId: string, state = "RUNNING"): Response {
  return jsonResponse({
    run: {
      runId,
      workspaceId: "workspace",
      sessionId: "session",
      harness: "claude",
      state,
      createdAt: "2026-06-20T12:00:00Z",
    },
  });
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
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:stale"));
    window.history.pushState({}, "", "/canvas");
    const runs = deferred<Response>();
    installMockTransport((path) =>
      path === "/v1/runs/run-stale" ? runs.promise : jsonResponse({ items: [], nextCursor: null }),
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

  it("keeps a remembered captured run through per-id lookup when it is attachable", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:live", "run-live");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:live"));
    window.history.pushState({}, "", "/canvas");
    const paths: string[] = [];
    installMockTransport((path) => {
      paths.push(path);
      return path === "/v1/runs/run-live"
        ? runLookupResponse("run-live")
        : jsonResponse({ items: [], nextCursor: null });
    });

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:live"));
    expect(paths).toContain("/v1/runs/run-live");
    expect(paths).not.toContain("/v1/runs");
    expect(useCapturedRunStore.getState().runs["claude:live"]?.runId).toBe("run-live");
    expect(useCanvasStore.getState().panes["claude:live"]).toBeDefined();
  });

  it("keeps a remembered STARTING captured run because backend attach accepts it", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:starting", "run-starting");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:starting"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs/run-starting"
        ? runLookupResponse("run-starting", "STARTING")
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:starting"));
    expect(useCapturedRunStore.getState().runs["claude:starting"]?.runId).toBe("run-starting");
    expect(useCanvasStore.getState().panes["claude:starting"]).toBeDefined();
  });

  it("keeps a remembered captured run that would be beyond the first list page", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:page-2", "run-page-2");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:page-2"));
    window.history.pushState({}, "", "/canvas");
    const paths: string[] = [];
    installMockTransport((path) => {
      paths.push(path);
      return path === "/v1/runs/run-page-2"
        ? runLookupResponse("run-page-2")
        : jsonResponse({ items: [], nextCursor: null });
    });

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:page-2"));
    expect(paths).not.toContain("/v1/runs");
    expect(useCapturedRunStore.getState().runs["claude:page-2"]?.runId).toBe("run-page-2");
    expect(useCanvasStore.getState().panes["claude:page-2"]).toBeDefined();
  });

  it("prunes absent start-candidate run ids from the run store and open or docked panes", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:open", "run-open");
    rememberCapturedRun("claude:docked", "run-docked");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:open"));
    useCanvasStore.getState().dockPane(makeCapturedRunRef("claude:docked"));
    window.history.pushState({}, "", "/canvas");
    const paths: string[] = [];
    installMockTransport((path) => {
      paths.push(path);
      if (path === "/v1/runs/run-open" || path === "/v1/runs/run-docked") {
        return jsonResponse({ detail: "missing" }, 404);
      }
      return jsonResponse({ items: [], nextCursor: null });
    });

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(useCapturedRunStore.getState().runs["claude:open"]).toBeUndefined();
      expect(useCapturedRunStore.getState().runs["claude:docked"]).toBeUndefined();
    });
    expect(useCanvasStore.getState().panes["claude:open"]).toBeUndefined();
    expect(useCanvasStore.getState().docked).toHaveLength(0);
    expect(paths).not.toContain("/v1/runs");
    expect(paths.some((path) => path.includes("/terminate"))).toBe(false);
    expect(capturedRunPaneRender).not.toHaveBeenCalled();
  });

  it("prunes a terminal remembered run without mounting captured content", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:exited", "run-exited");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:exited"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs/run-exited"
        ? runLookupResponse("run-exited", "EXITED")
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(useCapturedRunStore.getState().runs["claude:exited"]).toBeUndefined();
    });
    expect(useCanvasStore.getState().panes["claude:exited"]).toBeUndefined();
    expect(capturedRunPaneRender).not.toHaveBeenCalled();
  });

  it("preserves a captured run persisted during the reconciliation round trip", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:old", "run-old");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:old"));
    window.history.pushState({}, "", "/canvas");
    const runs = deferred<Response>();
    installMockTransport((path) =>
      path === "/v1/runs/run-old" ? runs.promise : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);
    await screen.findByTestId("captured-run-reconciliation-placeholder");

    act(() => {
      rememberCapturedRun("claude:new", "run-new");
      useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:new"));
    });
    await act(async () => {
      runs.resolve(jsonResponse({ detail: "missing" }, 404));
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

  it("keeps local captured run state and releases the gate when reconciliation fails", async () => {
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:kept", "run-kept");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:kept"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs/run-kept"
        ? jsonResponse({ detail: "backend unavailable" }, 503)
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:kept"));
    expect(useCapturedRunStore.getState().runs["claude:kept"]?.runId).toBe("run-kept");
    expect(useCanvasStore.getState().panes["claude:kept"]).toBeDefined();
  });

  it("keeps local state and releases the gate when reconciliation times out", async () => {
    vi.useFakeTimers();
    resetCanvasStoreForTests();
    resetCapturedRunStoreForTests();
    rememberCapturedRun("claude:hung", "run-hung");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:hung"));
    window.history.pushState({}, "", "/canvas");
    installMockTransport((path) =>
      path === "/v1/runs/run-hung"
        ? new Promise<Response>(() => {})
        : jsonResponse({ items: [], nextCursor: null }),
    );

    renderWithQuery(<SessionCanvasRoute />);
    expect(screen.getByTestId("captured-run-reconciliation-placeholder")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(capturedRunPaneRender).toHaveBeenCalledWith("claude:hung");
    expect(useCapturedRunStore.getState().runs["claude:hung"]?.runId).toBe("run-hung");
    expect(useCanvasStore.getState().panes["claude:hung"]).toBeDefined();
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
