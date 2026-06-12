import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { EngineLayoutState } from "../../engine";
import { clearDropTarget, setDropTarget } from "../dnd/dropTargetStore";
import { CanvasDropTargetOverlay } from "./CanvasDropTargetOverlay";

const LAYOUT: EngineLayoutState = {
  mode: "floating",
  viewport: { panX: 10, panY: 20, scale: 2 },
  focusedPaneId: null,
  order: ["t1"],
  nodes: {
    t1: {
      paneId: "t1",
      lifecycle: "open",
      rect: { x: 10, y: 15, width: 100, height: 40 },
      z: 1,
      pinned: false,
    },
  },
};

describe("CanvasDropTargetOverlay", () => {
  afterEach(() => clearDropTarget());

  it("maps a terminal target through the viewport camera", () => {
    setDropTarget({ kind: "terminal", paneId: "t1", label: "Claude-1" });

    render(<CanvasDropTargetOverlay layout={LAYOUT} />);

    const target = screen.getByText("Paste into Claude-1").parentElement;
    expect(target).toHaveClass("canvas-drop-target--terminal");
    expect(target).toHaveStyle({ left: "30px", top: "50px", width: "200px", height: "80px" });
  });

  it("renders the full-surface variant", () => {
    setDropTarget({ kind: "surface" });

    const { container } = render(<CanvasDropTargetOverlay layout={LAYOUT} />);

    expect(container.firstElementChild).toHaveClass("canvas-drop-target--surface");
  });

  it("renders nothing for null, hint, and missing terminal targets", () => {
    const { container, rerender } = render(<CanvasDropTargetOverlay layout={LAYOUT} />);
    expect(container).toBeEmptyDOMElement();

    setDropTarget({ kind: "hint" });
    rerender(<CanvasDropTargetOverlay layout={LAYOUT} />);
    expect(container).toBeEmptyDOMElement();

    setDropTarget({ kind: "terminal", paneId: "missing", label: "Ghost" });
    rerender(<CanvasDropTargetOverlay layout={LAYOUT} />);
    expect(container).toBeEmptyDOMElement();
  });
});
