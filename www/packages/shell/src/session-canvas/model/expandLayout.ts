import type { CanvasViewport, PaneId, ViewportBounds, WorldRect } from "../../engine";
import { resolveLayout } from "../../engine/layout";

export const EXPAND_LAYOUT = {
  marginX: 48,
  marginY: 48,
  columnGap: 24,
  leftRatio: 0.45,
} as const;

export const EXPAND_REMAINDER_STRATEGY_ID = "grid-overflow";

export interface ExpandLayoutInput {
  paneIds: readonly PaneId[];
  expandedPaneId: PaneId;
  viewport: ViewportBounds;
}

export interface ExpandLayoutResult {
  rects: Record<PaneId, WorldRect>;
  frame: WorldRect;
  camera: CanvasViewport;
}

export interface ExpandColumns {
  hero: WorldRect;
  remainder: WorldRect;
}

export function planExpandLayout(input: ExpandLayoutInput): ExpandLayoutResult {
  const { paneIds, expandedPaneId, viewport } = input;
  const remainderPaneIds = paneIds.filter((paneId) => paneId !== expandedPaneId);
  const columns = splitExpandColumns(viewport);
  const remainderStrategy = resolveLayout(EXPAND_REMAINDER_STRATEGY_ID);
  const params = remainderStrategy.defaults;
  const remainder = remainderStrategy.plan(
    { paneIds: remainderPaneIds, viewport: columns.remainder },
    params,
  );
  const remainderRects = translateRects(remainder.rects, columns.remainder);
  const remainderFrame = translateRect(
    remainder.frame ?? {
      x: 0,
      y: 0,
      width: columns.remainder.width,
      height: columns.remainder.height,
    },
    columns.remainder,
  );
  const frame = composeExpandFrame(columns.hero, remainderFrame, viewport);

  return {
    rects: {
      ...remainderRects,
      [expandedPaneId]: columns.hero,
    },
    frame,
    camera: fitExpandFrameCamera(frame, viewport),
  };
}

export function splitExpandColumns(viewport: ViewportBounds): ExpandColumns {
  const { columnGap, leftRatio, marginX, marginY } = EXPAND_LAYOUT;
  const innerW = Math.max(0, viewport.width - 2 * marginX - columnGap);
  const visibleContentH = Math.max(0, viewport.height - 2 * marginY);
  const heroW = innerW * leftRatio;
  const remainderW = innerW - heroW;
  return {
    hero: {
      x: marginX,
      y: marginY,
      width: heroW,
      height: visibleContentH,
    },
    remainder: {
      x: marginX + heroW + columnGap,
      y: marginY,
      width: remainderW,
      height: visibleContentH,
    },
  };
}

export function translateRect(rect: WorldRect, origin: WorldRect): WorldRect {
  return {
    x: origin.x + rect.x,
    y: origin.y + rect.y,
    width: rect.width,
    height: rect.height,
  };
}

export function translateRects(
  rects: Record<PaneId, WorldRect>,
  origin: WorldRect,
): Record<PaneId, WorldRect> {
  const translated: Record<PaneId, WorldRect> = {};
  for (const [paneId, rect] of Object.entries(rects)) {
    translated[paneId] = translateRect(rect, origin);
  }
  return translated;
}

export function composeExpandFrame(
  hero: WorldRect,
  remainderFrame: WorldRect,
  viewport: ViewportBounds,
): WorldRect {
  const contentBottom = Math.max(hero.y + hero.height, remainderFrame.y + remainderFrame.height);
  return {
    x: 0,
    y: 0,
    width: viewport.width,
    height: Math.max(viewport.height, contentBottom + EXPAND_LAYOUT.marginY),
  };
}

export function fitExpandFrameCamera(frame: WorldRect, viewport: ViewportBounds): CanvasViewport {
  const scale = Math.min(1, viewport.width / frame.width);
  return {
    scale,
    panX: viewport.width / 2 - (frame.x + frame.width / 2) * scale,
    panY: -frame.y * scale,
  };
}
