import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  resetCanvasGestureStoreForTests,
  setCanvasGestureModifier,
} from "../../keybindings/gestures";
import type { CanvasViewport } from "../types";
import { useCanvasViewport } from "./useCanvasViewport";

const INITIAL_VIEWPORT: CanvasViewport = { panX: 0, panY: 0, scale: 1 };

function ViewportProbe({ onSetViewport }: { onSetViewport: (viewport: CanvasViewport) => void }) {
  const [viewport, setViewportState] = useState(INITIAL_VIEWPORT);
  const controls = useCanvasViewport(viewport, {
    setViewport: (next) => {
      setViewportState(next);
      onSetViewport(next);
    },
  });

  return (
    <section
      {...controls.bindViewport()}
      data-pan-ready={controls.panReady ? "true" : "false"}
      aria-label="Viewport probe"
      data-testid="viewport"
      onKeyDown={controls.handleKeyDown}
      onWheel={controls.handleWheel}
      role="application"
    />
  );
}

describe("useCanvasViewport", () => {
  afterEach(() => {
    cleanup();
    resetCanvasGestureStoreForTests();
    vi.restoreAllMocks();
  });

  it("reads the configured gesture modifier for wheel zoom and pan readiness", () => {
    const onSetViewport = vi.fn();
    render(<ViewportProbe onSetViewport={onSetViewport} />);
    const viewport = screen.getByTestId("viewport");

    fireEvent.wheel(viewport, { clientX: 80, clientY: 60, deltaY: 10 });
    expect(onSetViewport).not.toHaveBeenCalled();

    fireEvent.wheel(viewport, { clientX: 80, clientY: 60, deltaY: 10, shiftKey: true });
    expect(onSetViewport).toHaveBeenCalledTimes(1);

    onSetViewport.mockClear();
    act(() => setCanvasGestureModifier("Space"));
    fireEvent.wheel(viewport, { clientX: 80, clientY: 60, deltaY: 10, shiftKey: true });
    expect(onSetViewport).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { code: "Space", key: " " });
    expect(viewport).toHaveAttribute("data-pan-ready", "true");

    fireEvent.wheel(viewport, { clientX: 80, clientY: 60, deltaY: 10 });
    expect(onSetViewport).toHaveBeenCalledTimes(1);
  });
});
