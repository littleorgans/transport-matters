import { truncateMiddle } from "@tm/core";
import {
  type DragEvent,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { PaneId } from "../../engine";
import { useDockKeybindings } from "../../keybindings/engine";
import { clearActiveDockDrag, PANE_REF_MIME, setActiveDockDrag } from "../dnd/dockDragSource";
import { clearDropTarget } from "../dnd/dropTargetStore";
import type { DockedPane } from "../model/paneRecords";
import { titleForRef } from "../viewers/registry";
import "./pane-dock.css";

/** Row labels middle-truncate (file names discriminate at both ends); full title on hover. */
const DOCK_TITLE_MAX = 44;

// Canvas-resident dock: a count-badged chip in the viewport's top band whose menu lists the locally
// minimized panes; selecting one restores it. Sourced ONLY from local minimized state (Option A),
// no GET /v1/runs, no liveness polling, no per-row attach or terminate. Screen-space and rendered through
// LayoutCanvas's overlay slot, so it is immune to pan/zoom and survives the lab top-bar TAB hide.
// Shared (components/, not lab/) so lab and production render the same dock affordance.
export interface PaneDockProps {
  docked: DockedPane[];
  onRestore(paneId: PaneId): void;
  /** Close/kill a docked pane without restoring it (captured-run -> kills the run). */
  onClose(paneId: PaneId): void;
}

export function PaneDock({ docked, onRestore, onClose }: PaneDockProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const closeDock = useCallback(() => setOpen(false), []);
  useDockKeybindings({ close: closeDock, isOpen: () => open });

  // Dismiss the menu on outside click so it never lingers over the canvas.
  // Escape is registered with the desktop keybinding engine.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  const restore = useCallback(
    (paneId: PaneId) => {
      onRestore(paneId);
      setOpen(false);
    },
    [onRestore],
  );

  // Close/kill a docked entry in place; keep the menu open so several can be cleared in one pass
  // (PaneDock unmounts itself once the dock empties).
  const close = useCallback((paneId: PaneId) => onClose(paneId), [onClose]);

  // Empty dock = no chip. Hooks above run unconditionally so this early return is rule-of-hooks safe.
  if (docked.length === 0) return null;

  // Screen-space overlay: swallow pointer/wheel so a click or scroll on the dock never pans or zooms
  // the canvas underneath it.
  const swallow = (event: SyntheticEvent) => event.stopPropagation();

  // Dock drag-out (doc 18): each row is an HTML5 drag source riding the same
  // surface dragover/drop pipeline as external file drags. The payload mime
  // carries the restore address; the module-scoped holder mirrors it for the
  // dragover resolver, which cannot read the payload in protected mode.
  const rowDragStart = (pane: DockedPane) => (event: DragEvent<HTMLDivElement>) => {
    // The kill button opts out: closing an entry is never read as the start of
    // a drag. Backstop to the button's draggable={false} + pointer-down guard,
    // for engines that surface the press target through the bubbled dragstart.
    if (event.target instanceof HTMLElement && event.target.closest(".canvas-dock__kill")) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.setData(
      PANE_REF_MIME,
      JSON.stringify({ paneId: pane.paneId, ref: pane.ref }),
    );
    // copyMove, not copy: the dragover resolver advertises move over the
    // surface (restore) and copy over a terminal (paste); an effectAllowed
    // narrower than the advertised dropEffect would veto the drop outright.
    event.dataTransfer.effectAllowed = "copyMove";
    setActiveDockDrag({ paneId: pane.paneId, ref: pane.ref });
  };
  // Fires with or without a drop, including Escape-cancel and releases outside
  // any surface: never strand the holder or the overlay (the safe default is
  // no state change, the entry stays docked).
  const rowDragEnd = () => {
    clearActiveDockDrag();
    clearDropTarget();
  };
  // Native engines determine the drag source from the press, not the bubbled
  // dragstart target: cancel the press default so a [×] grab never lifts the
  // row (the click still fires), and keep it off the canvas like the root.
  const killPointerDown = (event: SyntheticEvent) => {
    event.stopPropagation();
    event.preventDefault();
  };

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
            {docked.map((pane) => {
              const title = pane.record?.title ?? (pane.ref ? titleForRef(pane.ref) : pane.paneId);
              return (
                // biome-ignore lint/a11y/noStaticElementInteractions: drag-out is a pointer-only affordance; the menuitem buttons inside own every keyboard interaction.
                <div
                  className="canvas-dock__row"
                  draggable
                  key={pane.paneId}
                  onDragEnd={rowDragEnd}
                  onDragStart={rowDragStart(pane)}
                >
                  <button
                    className="canvas-dock__restore"
                    onClick={() => restore(pane.paneId)}
                    role="menuitem"
                    title={title}
                    type="button"
                  >
                    <span className="canvas-dock__title">
                      {truncateMiddle(title, DOCK_TITLE_MAX)}
                    </span>
                  </button>
                  <button
                    aria-label={`Close ${title}`}
                    className="canvas-dock__kill"
                    disabled={pane.closeDisabled}
                    draggable={false}
                    onClick={() => close(pane.paneId)}
                    onPointerDown={killPointerDown}
                    role="menuitem"
                    type="button"
                  >
                    {"×"}
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}
