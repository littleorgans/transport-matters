import type { WorldRect } from "../../types";
import { registerLayout } from "../registry";
import type { Control, LayoutParams, PlanInput, PlanResult } from "../types";

export interface GridOverflowParams extends LayoutParams {
  minW: number;
  minH: number;
  maxH: number;
  aspect: number;
  gap: number;
}

const DEFAULTS: GridOverflowParams = {
  minW: 300,
  minH: 220,
  maxH: 320,
  aspect: 4 / 3,
  gap: 16,
};

const CONTROLS: readonly Control[] = [
  { kind: "number", key: "minW", label: "Min width", min: 160, max: 640, step: 20 },
  { kind: "number", key: "minH", label: "Min height", min: 120, max: 560, step: 20 },
  { kind: "number", key: "maxH", label: "Max height", min: 120, max: 640, step: 20 },
  { kind: "number", key: "aspect", label: "Aspect", min: 0.5, max: 2.5, step: 0.05 },
  { kind: "number", key: "gap", label: "Gap", min: 0, max: 64, step: 4 },
];

export function planGridOverflow(input: PlanInput, params: GridOverflowParams): PlanResult {
  const { paneIds, viewport } = input;
  const count = paneIds.length;
  if (count === 0) return { rects: {} };

  const { aspect, gap, maxH, minH, minW } = params;
  const cols = Math.max(1, Math.floor((viewport.width + gap) / (minW + gap)));
  const cellW = (viewport.width - (cols - 1) * gap) / cols;
  const minCellH = Math.min(minH, maxH);
  const maxCellH = Math.max(minH, maxH);
  const cellH = Math.min(maxCellH, Math.max(minCellH, cellW / aspect));
  const rows = Math.ceil(count / cols);
  const rects: Record<string, WorldRect> = {};

  paneIds.forEach((paneId, index) => {
    const row = Math.floor(index / cols);
    const col = index % cols;
    rects[paneId] = {
      x: col * (cellW + gap),
      y: row * (cellH + gap),
      width: cellW,
      height: cellH,
    };
  });

  const contentH = rows * cellH + (rows - 1) * gap;
  const frame: WorldRect = {
    x: 0,
    y: 0,
    width: viewport.width,
    height: Math.max(viewport.height, contentH),
  };

  return { rects, reason: `grid-overflow ${cols}x${rows}`, frame };
}

registerLayout({
  id: "grid-overflow",
  label: "Grid (overflow)",
  defaults: DEFAULTS,
  controls: CONTROLS,
  plan: planGridOverflow,
});
