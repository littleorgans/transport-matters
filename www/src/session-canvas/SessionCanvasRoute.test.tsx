import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetCanvasStoreForTests, useCanvasStore } from "./model/canvasStore";
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

class MockEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();
}

describe("SessionCanvasRoute", () => {
  afterEach(() => {
    restoreTransport();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the picker immediately", async () => {
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<SessionCanvasRoute />);

    expect(screen.getByRole("toolbar", { name: "Canvas commands" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("No sessions found for this canvas.")).toBeInTheDocument(),
    );
  });

  it("auto resolves the launched run into the transcript seam", async () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ session_id: "session-live", run_id: "run-live" });
    window.history.pushState(
      {},
      "",
      "/canvas?owner=local&workspace_hash=hash-1&cli=claude&run_id=run-live",
    );
    vi.stubGlobal("EventSource", MockEventSource);
    installMockTransport((path) =>
      path.includes("/events?")
        ? jsonResponse({
            events: [makeSessionEvent({ session_id: "session-live" })],
            next_from_seq: null,
          })
        : jsonResponse([session]),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(screen.getByText("hello transcript")).toBeInTheDocument();
    });
  });

  it("feeds surface resize bounds into canvas planning", async () => {
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));
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
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<SessionCanvasRoute />);
    act(() => {
      useCanvasStore
        .getState()
        .spawnOrFocusTranscript(makeSessionSummary({ session_id: "abc", title: "Project agent" }));
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
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<SessionCanvasRoute />);
    act(() => {
      useCanvasStore
        .getState()
        .spawnOrFocusTranscript(makeSessionSummary({ session_id: "abc", title: "Project agent" }));
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
