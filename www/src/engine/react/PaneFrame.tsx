import { useDrag } from "@use-gesture/react";
import { motion, useReducedMotion } from "framer-motion";
import { useRef } from "react";
import { moveRect, resizeRect } from "../reducers/paneLifecycle";
import type { PaneNode, WorldRect } from "../types";

export interface PaneFrameProps {
  node: PaneNode;
  focused: boolean;
  titleId: string;
  onFocus(paneId: string): void;
  onMove(paneId: string, rect: WorldRect): void;
  onResize(paneId: string, rect: WorldRect): void;
  children: React.ReactNode;
}

const MINIMUM_PANE_RECT = { width: 300, height: 220 };
const NORMAL_TRANSITION = { type: "spring", stiffness: 360, damping: 38 } as const;
const REDUCED_TRANSITION = { duration: 0 } as const;

type DragMode = "move" | "resize";

export function PaneFrame({
  node,
  focused,
  titleId,
  onFocus,
  onMove,
  onResize,
  children,
}: PaneFrameProps) {
  const prefersReducedMotion = useReducedMotion();
  const dragMode = useRef<DragMode | null>(null);

  const bindDrag = useDrag(
    ({ delta: [deltaX, deltaY], event, first, last }) => {
      const target = event.target;
      if (first) dragMode.current = dragModeForTarget(target);
      if (!dragMode.current) return;
      event.stopPropagation();
      onFocus(node.paneId);
      const scale = currentWorldScale(event.currentTarget);
      const worldDeltaX = deltaX / scale;
      const worldDeltaY = deltaY / scale;
      if (dragMode.current === "move") {
        onMove(node.paneId, moveRect(node.rect, worldDeltaX, worldDeltaY));
      } else {
        onResize(node.paneId, resizeRect(node.rect, worldDeltaX, worldDeltaY, MINIMUM_PANE_RECT));
      }
      if (last) dragMode.current = null;
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
      layoutId={node.paneId}
      onFocus={() => onFocus(node.paneId)}
      onPointerDown={() => onFocus(node.paneId)}
      role="region"
      style={{ height: node.rect.height, width: node.rect.width, zIndex: node.z }}
      tabIndex={0}
      transition={prefersReducedMotion ? REDUCED_TRANSITION : NORMAL_TRANSITION}
      animate={{
        opacity: node.lifecycle === "closing" ? 0 : 1,
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
