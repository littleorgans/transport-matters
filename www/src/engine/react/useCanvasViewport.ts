import { useDrag } from "@use-gesture/react";
import { useCallback } from "react";
import { panViewport, zoomViewportAt } from "../reducers/layoutState";
import type { CanvasViewport } from "../types";

export interface CanvasViewportActions {
  setViewport(viewport: CanvasViewport): void;
}

const WHEEL_ZOOM_FACTOR = 0.92;
const KEYBOARD_PAN_STEP = 64;
const KEYBOARD_ZOOM_IN = 1.1;
const KEYBOARD_ZOOM_OUT = 0.9;

export function useCanvasViewport(
  viewport: CanvasViewport,
  actions: CanvasViewportActions,
): {
  bindViewport: ReturnType<typeof useDrag>;
  handleWheel(event: React.WheelEvent<HTMLElement>): void;
  handleKeyDown(event: React.KeyboardEvent<HTMLElement>): void;
} {
  const setViewport = actions.setViewport;
  const bindViewport = useDrag(
    ({ delta: [deltaX, deltaY], event }) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-pane-frame='true']")) return;
      setViewport(panViewport(viewport, deltaX, deltaY));
    },
    { pointer: { capture: false } },
  );

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLElement>) => {
      if (!event.metaKey && !event.ctrlKey) return;
      event.preventDefault();
      const factor = event.deltaY > 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR;
      setViewport(zoomViewportAt(viewport, factor, event.clientX, event.clientY));
    },
    [setViewport, viewport],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        setViewport(
          zoomViewportAt(viewport, KEYBOARD_ZOOM_IN, window.innerWidth / 2, window.innerHeight / 2),
        );
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        setViewport(
          zoomViewportAt(
            viewport,
            KEYBOARD_ZOOM_OUT,
            window.innerWidth / 2,
            window.innerHeight / 2,
          ),
        );
        return;
      }
      if (!event.altKey) return;
      const panByKey: Record<string, [number, number] | undefined> = {
        ArrowLeft: [KEYBOARD_PAN_STEP, 0],
        ArrowRight: [-KEYBOARD_PAN_STEP, 0],
        ArrowUp: [0, KEYBOARD_PAN_STEP],
        ArrowDown: [0, -KEYBOARD_PAN_STEP],
      };
      const delta = panByKey[event.key];
      if (!delta) return;
      event.preventDefault();
      setViewport(panViewport(viewport, delta[0], delta[1]));
    },
    [setViewport, viewport],
  );

  return { bindViewport, handleWheel, handleKeyDown };
}
