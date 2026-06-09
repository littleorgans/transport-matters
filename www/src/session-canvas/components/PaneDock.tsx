import { type SyntheticEvent, useCallback, useEffect, useRef, useState } from "react";
import type { PaneId } from "../../engine";
import type { DockedPane } from "../model/paneRecords";
import { titleForRef } from "../viewers/registry";

// Canvas-resident dock: a count-badged chip in the viewport's top band whose menu lists the locally
// minimized panes; selecting one restores it. Sourced ONLY from local minimized state (Option A) —
// no GET /api/runs, no liveness polling, no per-row attach/stop. Screen-space and rendered through
// LayoutCanvas's overlay slot, so it is immune to pan/zoom and survives the lab top-bar TAB hide.
// Shared (components/, not lab/) so production can reuse it once it grows its own `docked` state.
export interface PaneDockProps {
  docked: DockedPane[];
  onRestore(paneId: PaneId): void;
}

export function PaneDock({ docked, onRestore }: PaneDockProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Dismiss the menu on outside click or Escape so it never lingers over the canvas.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const restore = useCallback(
    (paneId: PaneId) => {
      onRestore(paneId);
      setOpen(false);
    },
    [onRestore],
  );

  // Empty dock = no chip. Hooks above run unconditionally so this early return is rule-of-hooks safe.
  if (docked.length === 0) return null;

  // Screen-space overlay: swallow pointer/wheel so a click or scroll on the dock never pans or zooms
  // the canvas underneath it.
  const swallow = (event: SyntheticEvent) => event.stopPropagation();

  return (
    <div className="canvas-viewport-dock" onPointerDown={swallow} onWheel={swallow} ref={rootRef}>
      <div className="canvas-dock__anchor">
        <button
          aria-expanded={open}
          aria-haspopup="menu"
          aria-label={`Minimized panes, ${docked.length}`}
          className="canvas-dock__chip"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <span className="canvas-dock__label">Dock</span>
          <span className="canvas-dock__count">{docked.length}</span>
        </button>
        {open ? (
          <div aria-label="Minimized panes" className="canvas-dock__menu" role="menu">
            {docked.map((pane) => (
              <button
                className="canvas-dock__row"
                key={pane.paneId}
                onClick={() => restore(pane.paneId)}
                role="menuitem"
                type="button"
              >
                <span className="canvas-dock__title">
                  {pane.ref ? titleForRef(pane.ref) : pane.paneId}
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
