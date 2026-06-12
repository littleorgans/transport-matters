import { useDrag } from "@use-gesture/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { panViewport, zoomViewportAt } from "../reducers/layoutState";
import type { CanvasViewport } from "../types";

export interface CanvasViewportActions {
  setViewport(viewport: CanvasViewport): void;
}

const WHEEL_ZOOM_FACTOR = 0.92;
const KEYBOARD_PAN_STEP = 64;
const KEYBOARD_ZOOM_IN = 1.1;
const KEYBOARD_ZOOM_OUT = 0.9;
// How long after the last zoom wheel tick before pane transitions are re-enabled. Long enough to
// bridge the gap between wheel events in one continuous scroll, short enough to feel immediate.
const ZOOM_IDLE_MS = 120;

export interface CanvasViewportControls {
  bindViewport: ReturnType<typeof useDrag>;
  handleWheel(event: React.WheelEvent<HTMLElement>): void;
  handleKeyDown(event: React.KeyboardEvent<HTMLElement>): void;
  // Shift held: the canvas can show the pan affordance (grab cursor) before the drag begins.
  panReady: boolean;
  // A shift-drag is currently panning the canvas (grabbing cursor).
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
  const [panReady, setPanReady] = useState(false);
  const [panning, setPanning] = useState(false);
  const [zooming, setZooming] = useState(false);
  const zoomTimer = useRef<number | null>(null);

  // Track Shift globally so the grab cursor appears the moment the key is down, not only mid-drag.
  useEffect(() => {
    const sync = (event: KeyboardEvent) => setPanReady(event.shiftKey);
    const clear = () => setPanReady(false);
    window.addEventListener("keydown", sync);
    window.addEventListener("keyup", sync);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", sync);
      window.removeEventListener("keyup", sync);
      window.removeEventListener("blur", clear);
    };
  }, []);

  useEffect(
    () => () => {
      if (zoomTimer.current !== null) window.clearTimeout(zoomTimer.current);
    },
    [],
  );

  // Pan is shift-gated: a plain drag belongs to a pane (move/resize); Shift+drag pans the canvas from
  // anywhere, including over a pane.
  const bindViewport = useDrag(
    ({ shiftKey, first, last, delta: [deltaX, deltaY] }) => {
      if (last) {
        setPanning(false);
        return;
      }
      if (!shiftKey) return;
      if (first) setPanning(true);
      setViewport(panViewport(viewport, deltaX, deltaY));
    },
    { pointer: { capture: false } },
  );

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLElement>) => {
      if (!event.shiftKey) return;
      event.preventDefault();
      if (zoomLocked) return;
      // Shift+wheel: browsers often report the scroll on deltaX (horizontal) rather than deltaY.
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

  return { bindViewport, handleWheel, handleKeyDown, panReady, panning, zooming };
}
