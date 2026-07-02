import { useDrag } from "@use-gesture/react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  getCanvasGestureSnapshot,
  shouldPanNotDrag,
  subscribeCanvasGestureStore,
} from "../../keybindings/gestures";
import type { CanvasViewport } from "../types";
import {
  KEYBOARD_PAN_STEP,
  KEYBOARD_ZOOM_IN,
  KEYBOARD_ZOOM_OUT,
  panViewport,
  WHEEL_ZOOM_FACTOR,
  zoomViewportAt,
} from "../viewport";

export interface CanvasViewportActions {
  setViewport(viewport: CanvasViewport): void;
}

// How long after the last zoom wheel tick before pane transitions are re-enabled. Long enough to
// bridge the gap between wheel events in one continuous scroll, short enough to feel immediate.
const ZOOM_IDLE_MS = 120;

export interface CanvasViewportControls {
  bindViewport: ReturnType<typeof useDrag>;
  handleWheel(event: React.WheelEvent<HTMLElement>): void;
  handleKeyDown(event: React.KeyboardEvent<HTMLElement>): void;
  // Gesture modifier held: the canvas can show the pan affordance before the drag begins.
  panReady: boolean;
  // A modifier-drag is currently panning the canvas.
  panning: boolean;
  // A wheel zoom is in flight: pane transitions should go instant so the size FLIP does not
  // rubber-band against the per-tick scale change.
  zooming: boolean;
}

export interface CanvasViewportOptions {
  // A pane drag converts pointer deltas through one scale for its whole
  // duration; refusing zoom while it is live keeps that conversion exact.
  zoomLocked?: boolean;
}

export function useCanvasViewport(
  viewport: CanvasViewport,
  actions: CanvasViewportActions,
  options: CanvasViewportOptions = {},
): CanvasViewportControls {
  const setViewport = actions.setViewport;
  const zoomLocked = options.zoomLocked ?? false;
  const gesture = useSyncExternalStore(
    subscribeCanvasGestureStore,
    getCanvasGestureSnapshot,
    getCanvasGestureSnapshot,
  );
  const [panning, setPanning] = useState(false);
  const [zooming, setZooming] = useState(false);
  const zoomTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (zoomTimer.current !== null) window.clearTimeout(zoomTimer.current);
    },
    [],
  );

  // Pan is modifier-gated: a plain drag belongs to a pane, modifier+drag pans the canvas.
  const bindViewport = useDrag(
    ({ event, first, last, delta: [deltaX, deltaY] }) => {
      if (last) {
        setPanning(false);
        return;
      }
      if (!shouldPanNotDrag(event)) return;
      if (first) setPanning(true);
      setViewport(panViewport(viewport, deltaX, deltaY));
    },
    { pointer: { capture: false } },
  );

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLElement>) => {
      if (!shouldPanNotDrag(event)) return;
      event.preventDefault();
      if (zoomLocked) return;
      // Modifier+wheel: browsers often report horizontal scroll on deltaX rather than deltaY.
      const scroll = event.deltaY !== 0 ? event.deltaY : event.deltaX;
      const factor = scroll > 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR;
      setViewport(zoomViewportAt(viewport, factor, event.clientX, event.clientY));
      setZooming(true);
      if (zoomTimer.current !== null) window.clearTimeout(zoomTimer.current);
      zoomTimer.current = window.setTimeout(() => {
        zoomTimer.current = null;
        setZooming(false);
      }, ZOOM_IDLE_MS);
    },
    [setViewport, viewport, zoomLocked],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        if (zoomLocked) return;
        setViewport(
          zoomViewportAt(viewport, KEYBOARD_ZOOM_IN, window.innerWidth / 2, window.innerHeight / 2),
        );
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        if (zoomLocked) return;
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
    [setViewport, viewport, zoomLocked],
  );

  return {
    bindViewport,
    handleWheel,
    handleKeyDown,
    panReady: gesture.modifierHeld,
    panning,
    zooming,
  };
}
