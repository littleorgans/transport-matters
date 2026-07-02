import { useDrag } from "@use-gesture/react";
import { motion, type Transition, useReducedMotion } from "framer-motion";
import { useRef, useState } from "react";
import "./pane-frame.css";
import { shouldPanNotDrag } from "../../keybindings/gestures";
import { roundWorldPoint } from "../layout/geometry";
import { CLOSE_DELAY_MS } from "../reducers/layoutState";
import { moveRect, resizeRect } from "../reducers/paneLifecycle";
import type { PaneNode, WorldRect } from "../types";

// Prop bundle from a dnd adapter (session-canvas SortablePane): the engine
// stays dnd-kit-free and consumes plain values. `transform` is WORLD pixels,
// already through the sortableTransformToWorld seam; PaneFrame applies it
// 1:1 on top of the committed rect.
export interface PaneDndHandle {
  setNodeRef(element: HTMLElement | null): void;
  listeners?: React.HTMLAttributes<HTMLElement>;
  transform: { x: number; y: number } | null;
  isDragging: boolean;
}

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
  // Present when a dnd adapter owns this pane's move gesture; the use-gesture
  // move path then stays inert and only resize binds.
  dnd?: PaneDndHandle | null;
  onFocus(paneId: string): void;
  // Plain free move (floating consumers such as the stress route). Reorder on
  // strategy canvases goes through `dnd` instead.
  onMove?(paneId: string, rect: WorldRect): void;
  onMoveEnd?(paneId: string, rect: WorldRect): void;
  onResize(paneId: string, rect: WorldRect): void;
  children: React.ReactNode;
}

const MINIMUM_PANE_RECT = { width: 300, height: 220 };
const NORMAL_TRANSITION = { type: "spring", stiffness: 360, damping: 38 } as const;
export const LAYOUT_MOTION_MS = 320;
const LAYOUT_MOTION_TRANSITION = {
  duration: LAYOUT_MOTION_MS / 1000,
  ease: [0.22, 1, 0.36, 1],
} as const;
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
  dnd = null,
  onFocus,
  onMove,
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
  // Local drag override. During move and resize drags the box follows the pointer off this live rect,
  // but the store is left untouched until release, so content reflows exactly once on commit.
  const [liveRect, setLiveRect] = useState<WorldRect | null>(null);
  const moveBase = useRef<WorldRect | null>(null);
  const resizeBase = useRef<WorldRect | null>(null);

  const closing = node.lifecycle === "closing";
  const directDrag = dragging || (dnd?.isDragging ?? false);
  const baseTransition =
    prefersReducedMotion || instant || directDrag
      ? REDUCED_TRANSITION
      : layoutMotion
        ? LAYOUT_MOTION_TRANSITION
        : NORMAL_TRANSITION;
  const positionTransition = layoutMotion ? baseTransition : SNAP_TRANSITION;
  // opacity + scale spring on the way in (the reveal) and tween out on close (timed to removal). Both
  // collapse to instant under reduced motion.
  let revealTransition: Transition = baseTransition;
  if (closing && !prefersReducedMotion) revealTransition = EXIT_TRANSITION;

  // The box renders off the live resize/move rect while one is in flight, off the committed store
  // rect otherwise. children always read the store rect, so they hold pre-drag layout until commit.
  // A dnd transform rides on top: world-space deltas from the sortable strategy (siblings) or the
  // converted pointer delta (the lifted pane).
  const renderRect = liveRect ?? node.rect;
  const dndPosition = dndPanePosition(renderRect, dnd?.transform ?? null);

  const bindDrag = useDrag(
    ({ movement: [moveX, moveY], event, first, last }) => {
      // Modifier+drag belongs to the canvas (pan), not the pane: leave the pane where it is.
      if (shouldPanNotDrag(event)) return;
      const target = event.target;
      if (first) {
        const mode = dragModeForTarget(target, bodyDrag);
        // A dnd adapter owns the move gesture; use-gesture keeps resize only.
        dragMode.current = dnd !== null && mode === "move" ? null : mode;
      }
      if (!dragMode.current) return;
      event.stopPropagation();
      const scale = currentWorldScale(target);
      if (first) {
        setDragging(true);
        onFocus(node.paneId);
        if (dragMode.current === "move") moveBase.current = node.rect;
        if (dragMode.current === "resize") resizeBase.current = node.rect;
      }
      if (dragMode.current === "move") {
        // Plain free move for floating consumers: track locally, commit on release.
        const base = moveBase.current ?? node.rect;
        const next = moveRect(base, moveX / scale, moveY / scale);
        if (last) onMoveEnd?.(node.paneId, next);
        else {
          setLiveRect(next);
          onMove?.(node.paneId, next);
        }
      } else {
        // Resize tracks locally (liveRect drives the box 1:1) and commits to the store only on
        // release, so content holds its pre-drag layout and reflows once. Off cumulative movement
        // from the drag-start base, not per-tick deltas, since the store rect is frozen mid-drag.
        const base = resizeBase.current ?? node.rect;
        const next = resizeRect(base, moveX / scale, moveY / scale, MINIMUM_PANE_RECT);
        if (last) onResize(node.paneId, next);
        else setLiveRect(next);
      }
      if (last) {
        dragMode.current = null;
        moveBase.current = null;
        resizeBase.current = null;
        setLiveRect(null);
        setDragging(false);
      }
    },
    { pointer: { capture: false } },
  );

  const gestureProps = bindDrag();
  const dndPointerDown = dnd?.listeners?.onPointerDown;

  return (
    <motion.div
      aria-labelledby={titleId}
      aria-selected={focused}
      data-pane-body-drag={bodyDrag ? "true" : "false"}
      data-pane-frame="true"
      data-pane-id={node.paneId}
      // layout="size" FLIPs width/height only and leaves position to animate x/y below, so the
      // per-axis x/y transition (the position snap) is honoured. Full layout/layoutId would route
      // position through the layout projection and ignore it.
      layout="size"
      onFocus={() => onFocus(node.paneId)}
      onPointerDown={() => onFocus(node.paneId)}
      ref={dnd?.setNodeRef}
      role="region"
      style={{ height: renderRect.height, width: renderRect.width, zIndex: node.z }}
      tabIndex={0}
      // Per-axis transitions: size (layout) + reveal (default) spring. Position normally snaps so a
      // reflow does not fly panes across the screen; explicit layoutMotion lets mode changes such as
      // E/uE transform the pane rects, and makes the sortable sibling shift animate mid-drag.
      transition={{
        default: revealTransition,
        layout: baseTransition,
        x: directDrag ? SNAP_TRANSITION : positionTransition,
        y: directDrag ? SNAP_TRANSITION : positionTransition,
      }}
      // x/y MUST be in initial and equal the mount rect (framer zeroes any transform prop absent from
      // initial, which would fly the pane in from the origin). Born-at-slot keeps node.rect final on
      // mount, so initial x/y == animate x/y and a new pane only fades and scales in.
      initial={{ opacity: 0, scale: 0.96, x: node.rect.x, y: node.rect.y }}
      animate={{
        opacity: closing ? 0 : 1,
        scale: closing ? 0.96 : 1,
        x: dndPosition.x,
        y: dndPosition.y,
      }}
    >
      <div
        {...gestureProps}
        className="pane-frame__body"
        onPointerDown={(event: React.PointerEvent<HTMLDivElement>) => {
          (dndPointerDown as React.PointerEventHandler<HTMLDivElement> | undefined)?.(event);
          gestureProps.onPointerDown?.(event);
        }}
        style={{ touchAction: "none" }}
      >
        {children}
      </div>
    </motion.div>
  );
}

// Position the pane renders at. At rest the rect passes through untouched
// (planner output is already quantized at the planLayout chokepoint). While
// a dnd transform is live, the composed position quantizes through the shared
// world-geometry primitive: per-tick subpixel translates inside the scaled
// container leave compositor ghost trails (the damage rect misses the moving
// pane's edges).
export function dndPanePosition(
  rect: { x: number; y: number },
  transform: { x: number; y: number } | null,
): { x: number; y: number } {
  if (transform === null) return { x: rect.x, y: rect.y };
  return roundWorldPoint({ x: rect.x + transform.x, y: rect.y + transform.y });
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
