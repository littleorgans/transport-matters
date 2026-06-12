import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EngineLayoutState } from "../../engine";
import type { PaneContentRef } from "../model/paneRecords";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import { clearDropTarget, useDropTargetStore } from "./dropTargetStore";
import { useCanvasDropTargets } from "./useCanvasDropTargets";

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

function Harness({ bridge = false }: { bridge?: boolean }) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const { dropHint } = useCanvasDropTargets(surfaceRef, {
    getLayout: () => LAYOUT,
    contentRefFor: () => undefined,
    titleFor: (paneId) => (paneId === "terminal" ? "Claude-1" : paneId),
    spawnPane: vi.fn((ref: PaneContentRef) => `resource:${ref.kind}`),
    minimizePane: vi.fn(),
  });
  if (bridge) {
    window.transportMattersDesktop = {
      appName: "Transport Matters",
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
    fireDrag("drop", surface, { clientX: 300, clientY: 300 });
    expect(useDropTargetStore.getState().target).toBeNull();
    expect(
      screen.getByText("File drops need the desktop app. URL drags work here."),
    ).toBeInTheDocument();
  });
});

function fireDrag(
  type: "dragover" | "dragleave" | "drop",
  target: HTMLElement,
  init: { clientX: number; clientY: number },
): void {
  target.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400 }) as DOMRect;
  const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(event, "clientX", { value: init.clientX });
  Object.defineProperty(event, "clientY", { value: init.clientY });
  Object.defineProperty(event, "dataTransfer", {
    value: {
      files: [{} as File],
      getData: () => "",
      dropEffect: "copy",
    },
  });
  act(() => {
    target.dispatchEvent(event);
  });
}
