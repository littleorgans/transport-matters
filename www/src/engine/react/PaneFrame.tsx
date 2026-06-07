import { useDrag } from "@use-gesture/react";
import { motion, useReducedMotion } from "framer-motion";
import { useLayoutEffect, useRef, useState } from "react";
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
  onFocus(paneId: string): void;
  onMove(paneId: string, rect: WorldRect): void;
  onResize(paneId: string, rect: WorldRect): void;
  children: React.ReactNode;
}

const MINIMUM_PANE_RECT = { width: 300, height: 220 };
const NORMAL_TRANSITION = { type: "spring", stiffness: 360, damping: 38 } as const;
const REDUCED_TRANSITION = { duration: 0 } as const;
const SNAP_TRANSITION = { duration: 0 } as const;
// Exit fade/scale-out is a tween timed to the removal window, so the pane reaches opacity 0 exactly
// as removeNode unmounts it (a spring would still be mid-fade at removal and visibly pop).
const EXIT_TRANSITION = { duration: CLOSE_DELAY_MS / 1000, ease: "easeIn" } as const;
// A reflow move larger than this many of the pane's own dimensions reads as "flying across the
// screen" (e.g. a pane reassigned to another row / wrapping columns). Those snap; smaller moves
// (neighbours shuffling to reallocate space, a row sliding as cells resize) keep their spring.
const TELEPORT_DISTANCE_FACTOR = 0;

type DragMode = "move" | "resize";

export function PaneFrame({
  node,
  focused,
  titleId,
  instant = false,
  onFocus,
  onMove,
  onResize,
  children,
}: PaneFrameProps) {
  const prefersReducedMotion = useReducedMotion();
  const dragMode = useRef<DragMode | null>(null);
  // True while this pane is being directly moved or resized. Direct manipulation must track the
  // pointer 1:1, so all transitions go instant for the duration of the drag (otherwise the size FLIP
  // and position spring rubber-band behind the cursor).
  const [dragging, setDragging] = useState(false);

  // How far this pane is about to move on this render. Small moves animate (the lovely shuffle as
  // neighbours reallocate space, rows sliding as cells resize); a large move means the pane was
  // reassigned far away (wrapping to another row) and would "fly across the screen", so we snap it.
  const previousRect = useRef<WorldRect>(node.rect);
  const moved = Math.hypot(
    node.rect.x - previousRect.current.x,
    node.rect.y - previousRect.current.y,
  );
  const teleport = moved > Math.max(node.rect.width, node.rect.height) * TELEPORT_DISTANCE_FACTOR;
  useLayoutEffect(() => {
    previousRect.current = node.rect;
  }, [node.rect]);

  const closing = node.lifecycle === "closing";
  const baseTransition =
    prefersReducedMotion || instant || dragging ? REDUCED_TRANSITION : NORMAL_TRANSITION;
  // Position springs for normal moves, snaps for cross-screen teleports. Size (layout) keeps the base
  // transition, so a teleporting pane still resizes smoothly; only its translate is instant.
  const positionTransition = teleport ? SNAP_TRANSITION : baseTransition;
  // opacity + scale spring on the way in (the reveal) and tween out on close (timed to removal). Both
  // collapse to instant under reduced motion.
  let revealTransition = baseTransition;
  if (closing && !prefersReducedMotion) revealTransition = EXIT_TRANSITION;

  const bindDrag = useDrag(
    ({ delta: [deltaX, deltaY], event, first, last, shiftKey }) => {
      // Shift+drag belongs to the canvas (pan), not the pane: leave the pane where it is.
      if (shiftKey) return;
      const target = event.target;
      if (first) dragMode.current = dragModeForTarget(target);
      if (!dragMode.current) return;
      event.stopPropagation();
      if (first) setDragging(true);
      onFocus(node.paneId);
      const scale = currentWorldScale(event.currentTarget);
      const worldDeltaX = deltaX / scale;
      const worldDeltaY = deltaY / scale;
      if (dragMode.current === "move") {
        onMove(node.paneId, moveRect(node.rect, worldDeltaX, worldDeltaY));
      } else {
        onResize(node.paneId, resizeRect(node.rect, worldDeltaX, worldDeltaY, MINIMUM_PANE_RECT));
      }
      if (last) {
        dragMode.current = null;
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
      // per-axis x/y transition (the teleport snap) is honoured. Full layout/layoutId would route
      // position through the layout projection and ignore it.
      layout="size"
      onFocus={() => onFocus(node.paneId)}
      onPointerDown={() => onFocus(node.paneId)}
      role="region"
      style={{ height: node.rect.height, width: node.rect.width, zIndex: node.z }}
      tabIndex={0}
      // Per-axis transitions: size + reveal use the base spring; position springs for ordinary moves
      // and snaps (instant) for cross-screen teleports so a pane never flies between distant rows.
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
        x: node.rect.x,
        y: node.rect.y,
      }}
    >
      <div {...bindDrag()} className="h-full">
        {children}
      </div>
    </motion.div>
  );
}

function dragModeForTarget(target: EventTarget | null): DragMode | null {
  if (!(target instanceof Element)) return null;
  if (target.closest("[data-pane-resize-handle='true']")) return "resize";
  if (target.closest("[data-pane-drag-handle='true']")) return "move";
  return null;
}

function currentWorldScale(target: EventTarget | null): number {
  if (!(target instanceof Element)) return 1;
  const world = target.closest<HTMLElement>("[data-canvas-world='true']");
  const value = world?.dataset.canvasScale;
  const parsed = value ? Number.parseFloat(value) : 1;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}
