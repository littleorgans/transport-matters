import type { PaneId, ViewportBounds, WorldRect } from "../../engine";

export const EXPAND_LAYOUT = {
  marginX: 48,
  marginY: 48,
  columnGap: 24,
  gridGap: 16,
  leftRatio: 0.45,
  gridMinW: 300,
  gridMinH: 220,
  gridMaxH: 320,
  gridAspect: 4 / 3,
} as const;

export interface ExpandLayoutInput {
  paneIds: readonly PaneId[];
  expandedPaneId: PaneId;
  viewport: ViewportBounds;
}

export interface ExpandLayoutResult {
  rects: Record<PaneId, WorldRect>;
  frame: WorldRect;
}

export function planExpandedLayout(input: ExpandLayoutInput): ExpandLayoutResult {
  const { paneIds, expandedPaneId, viewport } = input;
  const stackIds = paneIds.filter((paneId) => paneId !== expandedPaneId);
  const columns = splitColumns(viewport);
  const stack = planRightColumn(stackIds, columns.right);
  const frameH = Math.max(viewport.height, stack.contentH + 2 * EXPAND_LAYOUT.marginY);

  return {
    rects: {
      ...stack.rects,
      [expandedPaneId]: columns.left,
    },
    frame: {
      x: 0,
      y: 0,
      width: viewport.width,
      height: frameH,
    },
  };
}

export function fitExpandFrameToWidth(frame: WorldRect, bounds: ViewportBounds) {
  const scale = Math.min(1, bounds.width / frame.width);
  return {
    scale,
    panX: bounds.width / 2 - (frame.x + frame.width / 2) * scale,
    panY: -frame.y * scale,
  };
}

function splitColumns(viewport: ViewportBounds): {
  left: WorldRect;
  right: WorldRect;
  visibleContentH: number;
} {
  const { columnGap, leftRatio, marginX, marginY } = EXPAND_LAYOUT;
  const innerW = Math.max(0, viewport.width - 2 * marginX - columnGap);
  const visibleContentH = Math.max(0, viewport.height - 2 * marginY);
  const leftW = innerW * leftRatio;
  const rightW = innerW - leftW;
  return {
    left: {
      x: marginX,
      y: marginY,
      width: leftW,
      height: visibleContentH,
    },
    right: {
      x: marginX + leftW + columnGap,
      y: marginY,
      width: rightW,
      height: visibleContentH,
    },
    visibleContentH,
  };
}

function planRightColumn(
  paneIds: readonly PaneId[],
  column: WorldRect,
): { rects: Record<PaneId, WorldRect>; contentH: number } {
  if (paneIds.length === 0) return { rects: {}, contentH: column.height };

  const { gridAspect, gridGap, gridMaxH, gridMinH, gridMinW } = EXPAND_LAYOUT;
  const cols = Math.max(1, Math.floor((column.width + gridGap) / (gridMinW + gridGap)));
  const cellW = (column.width - (cols - 1) * gridGap) / cols;
  const cellH = Math.min(gridMaxH, Math.max(gridMinH, cellW / gridAspect));
  const rows = Math.ceil(paneIds.length / cols);
  const rects: Record<PaneId, WorldRect> = {};

  paneIds.forEach((paneId, index) => {
    const row = Math.floor(index / cols);
    const col = index % cols;
    rects[paneId] = {
      x: column.x + col * (cellW + gridGap),
      y: column.y + row * (cellH + gridGap),
      width: cellW,
      height: cellH,
    };
  });

  return {
    rects,
    contentH: rows * cellH + (rows - 1) * gridGap,
  };
}
