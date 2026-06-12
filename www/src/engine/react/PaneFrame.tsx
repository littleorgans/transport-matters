import { useDrag } from "@use-gesture/react";
import { motion, type Transition, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { CLOSE_DELAY_MS } from "../reducers/layoutState";
import { moveRect, resizeRect } from "../reducers/paneLifecycle";
import type { PaneNode, WorldRect } from "../types";

export interface PaneFrameProps {
  node: PaneNode;
  focused: boolean;
  titleId: string;
  // When true, all transitions go instant. Set during a wheel zoom so the size FLIP does not
  // rubber-band against the per-tick scale change.
  instant?: boolean;
  // Opt-in for layout mode changes where the pane's world rect should visibly transform.
  layoutMotion?: boolean;
  bodyDrag?: boolean;
  onFocus(paneId: string): void;
  onMove(paneId: string, rect: WorldRect): void;
  onMoveCancel?(paneId: string): void;
  onMoveEnd?(paneId: string, rect: WorldRect): void;
  onResize(paneId: string, rect: WorldRect): void;
  children: React.ReactNode;
}

const MINIMUM_PANE_RECT = { width: 300, height: 220 };
const NORMAL_TRANSITION = { type: "spring", stiffness: 360, damping: 38 } as const;
const LAYOUT_MOTION_TRANSITION = { duration: 0.32, ease: [0.22, 1, 0.36, 1] } as const;
const REDUCED_TRANSITION = { duration: 0 } as const;
const SNAP_TRANSITION = { duration: 0 } as const;
// Exit fade/scale-out is a tween timed to the removal window, so the pane reaches opacity 0 exactly
// as removeNode unmounts it (a spring would still be mid-fade at removal and visibly pop).
const EXIT_TRANSITION = { duration: CLOSE_DELAY_MS / 1000, ease: "easeIn" } as const;

type DragMode = "move" | "resize";

export function PaneFrame({
  node,
  focused,
  titleId,
  instant = false,
  layoutMotion = false,
  bodyDrag = false,
  onFocus,
  onMove,
  onMoveCancel,
  onMoveEnd,
  onResize,
  children,
}: PaneFrameProps) {
  const prefersReducedMotion = useReducedMotion();
  const dragMode = useRef<DragMode | null>(null);
  // True while this pane is being directly moved or resized. Direct manipulation must track the
  // pointer 1:1, so all transitions go instant for the duration of the drag (otherwise the size FLIP
  // and position spring rubber-band behind the cursor).
  const [dragging, setDragging] = useState(false);
  // Local resize override. During a resize drag the box follows the handle off this live rect, but
  // the store is left untouched until release, so the content (which reads the store rect) holds its
  // pre-drag layout and reflows exactly once on commit. Leaving the store untouched also means no
  // other pane re-renders mid-resize. Null except while resizing. resizeBase is the rect captured at
  // drag start; the live rect is computed off the cumulative pointer movement from it, not per-tick
  // deltas, so a fixed store rect can never drift the accumulation.
  const [liveRect, setLiveRect] = useState<WorldRect | null>(null);
  const moveBase = useRef<WorldRect | null>(null);
  const resizeBase = useRef<WorldRect | null>(null);
  const cancelledRef = useRef(false);

  const closing = node.lifecycle === "closing";
  const baseTransition =
    prefersReducedMotion || instant || dragging
      ? REDUCED_TRANSITION
      : layoutMotion
        ? LAYOUT_MOTION_TRANSITION
        : NORMAL_TRANSITION;
  const positionTransition = layoutMotion ? baseTransition : SNAP_TRANSITION;
  // opacity + scale spring on the way in (the reveal) and tween out on close (timed to removal). Both
  // collapse to instant under reduced motion.
  let revealTransition: Transition = baseTransition;
  if (closing && !prefersReducedMotion) revealTransition = EXIT_TRANSITION;

  // The box renders off the live resize rect while one is in flight, off the committed store rect
  // otherwise. children always read the store rect, so they hold pre-drag layout until commit.
  const renderRect = liveRect ?? node.rect;

  useEffect(() => {
    if (!dragging) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || dragMode.current !== "move") return;
      cancelledRef.current = true;
      onMoveCancel?.(node.paneId);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dragging, node.paneId, onMoveCancel]);

  const bindDrag = useDrag(
    ({ movement: [moveX, moveY], event, first, last, shiftKey }) => {
      // Shift+drag belongs to the canvas (pan), not the pane: leave the pane where it is.
      if (shiftKey) return;
      const target = event.target;
      if (first) dragMode.current = dragModeForTarget(target, bodyDrag);
      if (!dragMode.current) return;
      if (cancelledRef.current) {
        if (last) {
          cancelledRef.current = false;
          dragMode.current = null;
          moveBase.current = null;
          resizeBase.current = null;
          setLiveRect(null);
          setDragging(false);
        }
        return;
      }
      event.stopPropagation();
      const scale = currentWorldScale(target);
      if (first) {
        setDragging(true);
        onFocus(node.paneId);
        if (dragMode.current === "move") moveBase.current = node.rect;
        if (dragMode.current === "resize") resizeBase.current = node.rect;
      }
      if (dragMode.current === "move") {
        // Move commits live: position is cheap and the pane must track the cursor as it travels. Off
        // cumulative movement from the drag-start base, not per-tick deltas, so render cadence cannot
        // drift the grabbed point away from the pointer.
        const base = moveBase.current ?? node.rect;
        onMove(node.paneId, moveRect(base, moveX / scale, moveY / scale));
      } else {
        // Resize tracks locally (liveRect drives the box 1:1) and commits to the store only on
        // release, so content holds its pre-drag layout and reflows once. Off cumulative movement
        // from the drag-start base, not per-tick deltas, since the store rect is now frozen.
        const base = resizeBase.current ?? node.rect;
        const next = resizeRect(base, moveX / scale, moveY / scale, MINIMUM_PANE_RECT);
        if (last) onResize(node.paneId, next);
        else setLiveRect(next);
      }
      if (last) {
        if (dragMode.current === "move") {
          const base = moveBase.current ?? node.rect;
          onMoveEnd?.(node.paneId, moveRect(base, moveX / scale, moveY / scale));
        }
        dragMode.current = null;
        moveBase.current = null;
        resizeBase.current = null;
        setLiveRect(null);
        setDragging(false);
      }
    },
    { pointer: { capture: false } },
  );

  return (
    <motion.div
      aria-labelledby={titleId}
      aria-selected={focused}
      className="absolute outline-none"
      data-pane-frame="true"
      data-pane-id={node.paneId}
      // layout="size" FLIPs width/height only and leaves position to animate x/y below, so the
      // per-axis x/y transition (the position snap) is honoured. Full layout/layoutId would route
      // position through the layout projection and ignore it.
      layout="size"
      onFocus={() => onFocus(node.paneId)}
      onPointerDown={() => onFocus(node.paneId)}
      role="region"
      style={{ height: renderRect.height, width: renderRect.width, zIndex: node.z }}
      tabIndex={0}
      // Per-axis transitions: size (layout) + reveal (default) spring. Position normally snaps so a
      // reflow does not fly panes across the screen; explicit layoutMotion lets mode changes such as
      // E/uE transform the pane rects.
      transition={{
        default: revealTransition,
        layout: baseTransition,
        x: positionTransition,
        y: positionTransition,
      }}
      // x/y MUST be in initial and equal the mount rect (framer zeroes any transform prop absent from
      // initial, which would fly the pane in from the origin). Born-at-slot keeps node.rect final on
      // mount, so initial x/y == animate x/y and a new pane only fades and scales in.
      initial={{ opacity: 0, scale: 0.96, x: node.rect.x, y: node.rect.y }}
      animate={{
        opacity: closing ? 0 : 1,
        scale: closing ? 0.96 : 1,
        x: renderRect.x,
        y: renderRect.y,
      }}
    >
      <div {...bindDrag()} className="h-full" style={{ touchAction: "none" }}>
        {children}
      </div>
    </motion.div>
  );
}

export function dragModeForTarget(target: EventTarget | null, bodyDrag: boolean): DragMode | null {
  if (!(target instanceof Element)) return null;
  if (target.closest("[data-pane-resize-handle='true']")) return "resize";
  if (target.closest("[data-pane-drag-handle='true']")) return "move";
  if (
    bodyDrag &&
    !target.closest("button, a, input, textarea, select, [data-pane-no-drag='true']")
  ) {
    return "move";
  }
  return null;
}

function currentWorldScale(target: EventTarget | null): number {
  if (!(target instanceof Element)) return 1;
  const world = target.closest<HTMLElement>("[data-canvas-world='true']");
  const value = world?.dataset.canvasScale;
  const parsed = value ? Number.parseFloat(value) : 1;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}
