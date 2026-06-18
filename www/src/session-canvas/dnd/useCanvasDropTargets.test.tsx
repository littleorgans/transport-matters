import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EngineLayoutState } from "../../engine";
import type { PaneContentRef } from "../model/paneRecords";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import {
  clearActiveDockDrag,
  PANE_REF_MIME,
  readActiveDockDrag,
  setActiveDockDrag,
} from "./dockDragSource";
import { clearDropTarget, useDropTargetStore } from "./dropTargetStore";
import { type CanvasDropTargetDeps, useCanvasDropTargets } from "./useCanvasDropTargets";

const LAYOUT: EngineLayoutState = {
  mode: "floating",
  viewport: { panX: 0, panY: 0, scale: 1 },
  focusedPaneId: null,
  order: ["terminal", "resource"],
  nodes: {
    terminal: {
      paneId: "terminal",
      lifecycle: "open",
      rect: { x: 0, y: 0, width: 100, height: 100 },
      z: 1,
      pinned: false,
    },
    resource: {
      paneId: "resource",
      lifecycle: "open",
      rect: { x: 160, y: 0, width: 100, height: 100 },
      z: 2,
      pinned: false,
    },
  },
};

function Harness({
  bridge = false,
  deps = {},
}: {
  bridge?: boolean;
  deps?: Partial<CanvasDropTargetDeps>;
}) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const { dropHint } = useCanvasDropTargets(surfaceRef, {
    getLayout: () => LAYOUT,
    contentRefFor: () => undefined,
    titleFor: (paneId) => (paneId === "terminal" ? "Claude-1" : paneId),
    spawnPane: vi.fn((ref: PaneContentRef) => `resource:${ref.kind}`),
    dockPane: vi.fn((ref: PaneContentRef) => `resource:${ref.kind}`),
    restorePaneAtIndex: vi.fn(),
    ...deps,
  });
  if (bridge) {
    window.transportMattersDesktop = {
      appName: "Transport Matters",
      platform: "darwin",
      getPathForFile: () => "/tmp/shot.png",
    };
  }
  return (
    <div data-testid="surface" ref={surfaceRef} style={{ height: 400, width: 400 }}>
      {dropHint ? <p>{dropHint}</p> : null}
    </div>
  );
}

describe("useCanvasDropTargets", () => {
  afterEach(() => {
    clearDropTarget();
    clearActiveDockDrag();
    delete window.transportMattersDesktop;
  });

  it("highlights a paste-handle pane during dragover", () => {
    const unregister = registerPasteHandle("terminal", vi.fn());
    render(<Harness />);

    fireDrag("dragover", screen.getByTestId("surface"), { clientX: 50, clientY: 50 });

    expect(useDropTargetStore.getState().target).toEqual({
      kind: "terminal",
      paneId: "terminal",
      label: "Claude-1",
    });
    unregister();
  });

  it("marks surface when the desktop bridge can resolve dropped files", () => {
    render(<Harness bridge />);

    fireDrag("dragover", screen.getByTestId("surface"), { clientX: 300, clientY: 300 });

    expect(useDropTargetStore.getState().target).toEqual({ kind: "surface" });
  });

  it("marks hint without a bridge, then clears on dragleave and drop", () => {
    render(<Harness />);
    const surface = screen.getByTestId("surface");

    fireDrag("dragover", surface, { clientX: 300, clientY: 300 });
    expect(useDropTargetStore.getState().target).toEqual({ kind: "hint" });

    fireDrag("dragleave", surface, { clientX: 300, clientY: 300 });
    expect(useDropTargetStore.getState().target).toBeNull();

    fireDrag("dragover", surface, { clientX: 300, clientY: 300 });
    fireDrag("drop", surface, {
      clientX: 300,
      clientY: 300,
      dataTransfer: makeDataTransfer({ files: [{} as File] }),
    });
    expect(useDropTargetStore.getState().target).toBeNull();
    expect(
      screen.getByText("File drops need the desktop app. URL drags work here."),
    ).toBeInTheDocument();
  });

  describe("dock drags (doc 18)", () => {
    const LOCATOR_REF = {
      kind: "resource",
      owner: "local",
      source: "path",
      path: "/t/x.png",
    } as const;

    it("targets a paste-handle pane for a locator-bearing holder, dropEffect copy", () => {
      const unregister = registerPasteHandle("terminal", vi.fn());
      setActiveDockDrag({ paneId: "resource:path:/t/x.png", ref: LOCATOR_REF });
      render(<Harness />);
      const transfer = makeDataTransfer({ types: [PANE_REF_MIME] });

      fireDrag("dragover", screen.getByTestId("surface"), {
        clientX: 50,
        clientY: 50,
        dataTransfer: transfer,
      });

      expect(useDropTargetStore.getState().target).toEqual({
        kind: "terminal",
        paneId: "terminal",
        label: "Claude-1",
      });
      expect(transfer.dropEffect).toBe("copy");
      unregister();
    });

    it("targets the surface over empty canvas with dropEffect move, never hint", () => {
      // no desktop bridge: an external Files drag here resolves to `hint`, but a
      // dock entry is already resolved in memory, in the plain browser too
      setActiveDockDrag({ paneId: "resource:path:/t/x.png", ref: LOCATOR_REF });
      render(<Harness />);
      const transfer = makeDataTransfer({ types: [PANE_REF_MIME] });

      fireDrag("dragover", screen.getByTestId("surface"), {
        clientX: 300,
        clientY: 300,
        dataTransfer: transfer,
      });

      expect(useDropTargetStore.getState().target).toEqual({ kind: "surface" });
      expect(transfer.dropEffect).toBe("move");
    });

    it("never targets a terminal for a non-locator holder, even over a paste handle", () => {
      const unregister = registerPasteHandle("terminal", vi.fn());
      setActiveDockDrag({ paneId: "lab-2", ref: null });
      render(<Harness />);

      fireDrag("dragover", screen.getByTestId("surface"), {
        clientX: 50,
        clientY: 50,
        dataTransfer: makeDataTransfer({ types: [PANE_REF_MIME] }),
      });

      expect(useDropTargetStore.getState().target).toEqual({ kind: "surface" });
      unregister();
    });

    it("routes a pane-ref drop to the dock handler: paste branch", () => {
      const paste = vi.fn();
      const unregister = registerPasteHandle("terminal", paste);
      const dockPane = vi.fn();
      const restorePaneAtIndex = vi.fn();
      const spawnPane = vi.fn();
      setActiveDockDrag({ paneId: "resource:path:/t/x.png", ref: LOCATOR_REF });
      render(<Harness deps={{ dockPane, restorePaneAtIndex, spawnPane }} />);

      fireDrag("drop", screen.getByTestId("surface"), {
        clientX: 50,
        clientY: 50,
        dataTransfer: makeDataTransfer({
          types: [PANE_REF_MIME],
          data: {
            [PANE_REF_MIME]: JSON.stringify({
              paneId: "resource:path:/t/x.png",
              ref: LOCATOR_REF,
            }),
          },
        }),
      });

      expect(paste).toHaveBeenCalledWith("/t/x.png");
      expect(dockPane).toHaveBeenCalledWith(LOCATOR_REF);
      expect(restorePaneAtIndex).not.toHaveBeenCalled();
      // never the external pipeline: a pane-ref drop must not spawn a new pane
      expect(spawnPane).not.toHaveBeenCalled();
      // drop clears the holder and the overlay
      expect(readActiveDockDrag()).toBeNull();
      expect(useDropTargetStore.getState().target).toBeNull();
      unregister();
    });

    it("routes a pane-ref drop to the dock handler: restore-at-index branch", () => {
      const restorePaneAtIndex = vi.fn();
      setActiveDockDrag({ paneId: "lab-2", ref: null });
      render(<Harness deps={{ restorePaneAtIndex }} />);

      // empty canvas at (300, 300): nearest center is `resource` -> its slot, index 1
      fireDrag("drop", screen.getByTestId("surface"), {
        clientX: 300,
        clientY: 300,
        dataTransfer: makeDataTransfer({
          types: [PANE_REF_MIME],
          data: { [PANE_REF_MIME]: JSON.stringify({ paneId: "lab-2", ref: null }) },
        }),
      });

      expect(restorePaneAtIndex).toHaveBeenCalledWith("lab-2", 1);
      expect(readActiveDockDrag()).toBeNull();
    });

    it("ignores a pane-ref drop whose payload does not parse", () => {
      const restorePaneAtIndex = vi.fn();
      const spawnPane = vi.fn();
      render(<Harness deps={{ restorePaneAtIndex, spawnPane }} />);

      fireDrag("drop", screen.getByTestId("surface"), {
        clientX: 300,
        clientY: 300,
        dataTransfer: makeDataTransfer({ types: [PANE_REF_MIME] }),
      });

      expect(restorePaneAtIndex).not.toHaveBeenCalled();
      expect(spawnPane).not.toHaveBeenCalled();
    });
  });
});

function fireDrag(
  type: "dragover" | "dragleave" | "drop",
  target: HTMLElement,
  init: { clientX: number; clientY: number; dataTransfer?: DataTransfer },
): void {
  target.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400 }) as DOMRect;
  const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(event, "clientX", { value: init.clientX });
  Object.defineProperty(event, "clientY", { value: init.clientY });
  Object.defineProperty(event, "dataTransfer", {
    value: init.dataTransfer ?? makeDataTransfer(),
  });
  act(() => {
    target.dispatchEvent(event);
  });
}

function makeDataTransfer(
  init: { files?: File[]; types?: string[]; data?: Record<string, string> } = {},
): DataTransfer {
  return {
    files: init.files ?? [],
    types: init.types ?? ["Files"],
    getData: (type: string) => init.data?.[type] ?? "",
    dropEffect: "copy",
  } as unknown as DataTransfer;
}
