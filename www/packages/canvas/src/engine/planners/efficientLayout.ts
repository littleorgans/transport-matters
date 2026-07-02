import { CANVAS_LAYOUT_MARGIN } from "../layout/types";
import type { LayoutMode, PaneId, ViewportBounds, WorldRect } from "../types";

export interface EfficientLayoutInput {
  paneIds: readonly PaneId[];
  currentRects: Readonly<Record<PaneId, WorldRect>>;
  viewport: ViewportBounds;
  mode: LayoutMode;
  focusedPaneId: PaneId | null;
  pinnedPaneIds?: readonly PaneId[];
}

export interface EfficientLayoutPlan {
  rects: Record<PaneId, WorldRect>;
  reason: string;
}

const WORLD_MARGIN = CANVAS_LAYOUT_MARGIN;
const PANE_GAP = 24;
const MIN_PANE_WIDTH = 320;
const MIN_PANE_HEIGHT = 240;
const FOCUS_RAIL_WIDTH = 180;

export function planEfficientLayout(input: EfficientLayoutInput): EfficientLayoutPlan {
  const pinned = new Set(input.pinnedPaneIds ?? []);
  if (input.mode === "focus" && input.focusedPaneId) {
    return planFocus(input, pinned);
  }
  return planFloatingGrid(input, pinned);
}

function planFloatingGrid(
  input: EfficientLayoutInput,
  pinned: ReadonlySet<PaneId>,
): EfficientLayoutPlan {
  const unpinned = input.paneIds.filter((paneId) => !pinned.has(paneId));
  const rects = copyPinnedRects(input, pinned);
  if (unpinned.length === 0) return { rects, reason: "pinned-only" };

  const columns = Math.max(1, Math.ceil(Math.sqrt(unpinned.length)));
  const rows = Math.max(1, Math.ceil(unpinned.length / columns));
  const width = Math.max(
    MIN_PANE_WIDTH,
    (input.viewport.width - WORLD_MARGIN * 2 - PANE_GAP * (columns - 1)) / columns,
  );
  const height = Math.max(
    MIN_PANE_HEIGHT,
    (input.viewport.height - WORLD_MARGIN * 2 - PANE_GAP * (rows - 1)) / rows,
  );

  unpinned.forEach((paneId, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    rects[paneId] = {
      x: WORLD_MARGIN + column * (width + PANE_GAP),
      y: WORLD_MARGIN + row * (height + PANE_GAP),
      width,
      height,
    };
  });

  return { rects, reason: "balanced-grid" };
}

function planFocus(input: EfficientLayoutInput, pinned: ReadonlySet<PaneId>): EfficientLayoutPlan {
  const rects = copyPinnedRects(input, pinned);
  const focused = input.focusedPaneId;
  const railIds = input.paneIds.filter((paneId) => paneId !== focused && !pinned.has(paneId));
  if (focused && !pinned.has(focused)) {
    rects[focused] = {
      x: WORLD_MARGIN,
      y: WORLD_MARGIN,
      width: Math.max(MIN_PANE_WIDTH, input.viewport.width - WORLD_MARGIN * 3 - FOCUS_RAIL_WIDTH),
      height: Math.max(MIN_PANE_HEIGHT, input.viewport.height - WORLD_MARGIN * 2),
    };
  }

  railIds.forEach((paneId, index) => {
    rects[paneId] = {
      x: input.viewport.width - WORLD_MARGIN - FOCUS_RAIL_WIDTH,
      y: WORLD_MARGIN + index * (MIN_PANE_HEIGHT + PANE_GAP),
      width: FOCUS_RAIL_WIDTH,
      height: MIN_PANE_HEIGHT,
    };
  });

  return { rects, reason: "focus-rails" };
}

function copyPinnedRects(
  input: EfficientLayoutInput,
  pinned: ReadonlySet<PaneId>,
): Record<PaneId, WorldRect> {
  const rects: Record<PaneId, WorldRect> = {};
  for (const paneId of input.paneIds) {
    const rect = input.currentRects[paneId];
    if (pinned.has(paneId) && rect) rects[paneId] = rect;
  }
  return rects;
}
