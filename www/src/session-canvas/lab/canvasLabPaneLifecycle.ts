import type { StoreApi } from "zustand";
import {
  CLOSE_DELAY_MS,
  DEFAULT_CANVAS_VIEWPORT,
  markNodeClosing,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
} from "../../engine";
import { resolvePaneLifecycle } from "../model/paneLifecycle";
import type { DockedPane } from "../model/paneRecords";
import {
  isZoomedInPastOverview,
  openPaneIds,
  planLayout,
  UNFRAME_FLY_PANE_LIMIT,
} from "./canvasLabLayout";
import type { CanvasLabState } from "./canvasLabTypes";

interface FlyOptions {
  paneMotion?: boolean;
}

type StartFly = (options?: FlyOptions) => void;
type CanvasLabStoreApi = Pick<StoreApi<CanvasLabState>, "getState" | "setState">;

// Minimize parks the pane in the dock for local restore; close discards it. The per-kind resource
// side effect (e.g. captured-run kill on close) is resolved through the lifecycle policy, not here.
export type PaneDismissMode = "minimize" | "close";

// Node + camera teardown shared by minimize and close. Remove the node, re-plan so survivors flow
// into the gap, and reflow the camera (collapse expand, leave a frame, or undo a manual zoom-in)
// exactly as before. Returns the layout/expanded/framing patch and triggers the fly side effects
// itself. A fitted close is reserved for those three cases; normal overview / zoomed-out closes keep
// the camera. Mirrors the production canvasStore close protocol.
function finalizePaneRemoval(
  state: CanvasLabState,
  paneId: PaneId,
  startFly: StartFly,
): Pick<CanvasLabState, "expandedPaneId" | "framing" | "layout"> {
  const collapsing = state.expandedPaneId === paneId;
  const unframing = state.framing.paneId === paneId;
  const expandedPaneId = collapsing ? null : state.expandedPaneId;
  const framing = collapsing || unframing ? { paneId: null, overview: null } : state.framing;
  const removed = removeNode(state.layout, paneId);
  let layout = planLayout(
    removed,
    state.bounds,
    state.activeStrategyId,
    state.params,
    collapsing,
    expandedPaneId,
  );
  if (collapsing) {
    startFly({ paneMotion: true });
  } else if (unframing) {
    startFly();
    layout = setEngineViewport(layout, state.framing.overview ?? DEFAULT_CANVAS_VIEWPORT);
  } else {
    const overviewLayout = planLayout(
      removed,
      state.bounds,
      state.activeStrategyId,
      state.params,
      true,
      expandedPaneId,
    );
    if (isZoomedInPastOverview(state.layout.viewport, overviewLayout.viewport)) {
      if (openPaneIds(layout).length <= UNFRAME_FLY_PANE_LIMIT) startFly();
      layout = overviewLayout;
    }
  }
  return { expandedPaneId, framing, layout };
}

// Shared two-phase teardown for both minimize and close. The exit animation and reflow are identical
// across kinds and modes; only the lifecycle hook (and whether the pane docks) differs. Mark the pane
// closing (it fades + scales out in place, neighbours hold their slots), then after the exit window
// run the resolved hook (close -> captured-run stopRun; minimize -> none today), dock it on minimize,
// drop the node, and reflow survivors into the gap.
export function dismissPane(
  store: CanvasLabStoreApi,
  paneId: PaneId,
  mode: PaneDismissMode,
  startFly: StartFly,
): void {
  store.setState((state) => ({ layout: markNodeClosing(state.layout, paneId) }));
  window.setTimeout(() => {
    const state = store.getState();
    const closingRef = state.contentRefs[paneId] ?? null;
    if (closingRef) {
      const policy = resolvePaneLifecycle(closingRef);
      if (mode === "close") policy.onClose?.(closingRef);
      else policy.onMinimize?.(closingRef);
    }
    const removal = finalizePaneRemoval(state, paneId, startFly);
    const { [paneId]: _closed, ...contentRefs } = state.contentRefs;
    // Minimize parks the pane in the dock (most-recent first) for local restore; close discards it.
    const docked: DockedPane[] =
      mode === "minimize" ? [{ paneId, ref: closingRef }, ...state.docked] : state.docked;
    store.setState({ ...removal, contentRefs, docked });
  }, CLOSE_DELAY_MS);
}
