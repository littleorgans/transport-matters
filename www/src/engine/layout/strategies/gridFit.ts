import type { ViewportBounds, WorldRect } from "../../types";
import { fitScale } from "../fit";
import { registerLayout } from "../registry";
import type { Control, LayoutParams, PlanInput, PlanResult } from "../types";

// Width-filling grid. The column count is chosen by SIMULATING the final on-screen result
// including the lab's zoom-to-fit, so a layout never leaves horizontal slack after zooming out.
interface GridFitParams extends LayoutParams {
  minW: number;
  minH: number;
  gap: number;
  margin: number;
  targetAspect: number;
  lastRow: "left" | "center";
}

const DEFAULTS: GridFitParams = {
  minW: 320,
  minH: 240,
  gap: 24,
  margin: 48,
  targetAspect: 4 / 3,
  lastRow: "left",
};

const CONTROLS: readonly Control[] = [
  { kind: "number", key: "minW", label: "Min width", min: 160, max: 640, step: 20 },
  { kind: "number", key: "minH", label: "Min height", min: 120, max: 560, step: 20 },
  { kind: "number", key: "gap", label: "Gap", min: 0, max: 64, step: 4 },
  { kind: "number", key: "margin", label: "Margin", min: 0, max: 120, step: 4 },
  { kind: "number", key: "targetAspect", label: "Target aspect", min: 0.5, max: 2.5, step: 0.05 },
  {
    kind: "enum",
    key: "lastRow",
    label: "Last row",
    options: [
      { value: "left", label: "Left-align" },
      { value: "center", label: "Center" },
    ],
  },
];

const TIE = 1e-6;

interface CellPlan {
  rows: number;
  cellW: number;
  cellH: number;
}

function cellsFor(
  count: number,
  cols: number,
  viewport: ViewportBounds,
  params: GridFitParams,
): CellPlan {
  const rows = Math.ceil(count / cols);
  const cellW = Math.max(
    params.minW,
    (viewport.width - (cols - 1) * params.gap - 2 * params.margin) / cols,
  );
  const cellH = Math.max(
    params.minH,
    (viewport.height - (rows - 1) * params.gap - 2 * params.margin) / rows,
  );
  return { rows, cellW, cellH };
}

// Pick the column count that maximizes displayed (post-zoom) pane area, penalized toward
// targetAspect. Replaces the old scale-1 capacity cap, which ignored the later zoom-to-fit and so
// left a horizontal band empty once the grid zoomed out to fit extra rows. Deterministic:
// tie-break is fewer rows, then fewer columns.
function selectColumns(count: number, viewport: ViewportBounds, params: GridFitParams): number {
  let bestCols = 0;
  let bestScore = Number.NEGATIVE_INFINITY;
  let bestRows = Number.POSITIVE_INFINITY;
  for (let cols = 1; cols <= count; cols += 1) {
    const { rows, cellW, cellH } = cellsFor(count, cols, viewport, params);
    const gridW = cols * cellW + (cols - 1) * params.gap;
    const gridH = rows * cellH + (rows - 1) * params.gap;
    const scale = fitScale(gridW, gridH, viewport);
    const displayedArea = cellW * scale * (cellH * scale);
    const aspectFactor = Math.exp(-Math.abs(Math.log(cellW / cellH / params.targetAspect)));
    const score = displayedArea * aspectFactor;
    const better =
      score > bestScore * (1 + TIE) ||
      (score >= bestScore * (1 - TIE) &&
        (rows < bestRows || (rows === bestRows && cols < bestCols)));
    if (bestCols === 0 || better) {
      bestScore = score;
      bestCols = cols;
      bestRows = rows;
    }
  }
  return bestCols;
}

export function planGridFit(input: PlanInput, params: GridFitParams): PlanResult {
  const { paneIds, viewport } = input;
  const count = paneIds.length;
  if (count === 0) return { rects: {} };

  const { gap, margin, lastRow } = params;
  const cols = selectColumns(count, viewport, params);
  const { rows, cellW, cellH } = cellsFor(count, cols, viewport, params);
  const usableW = viewport.width - 2 * margin;
  const lastRowIndex = rows - 1;

  const rects: Record<string, WorldRect> = {};
  paneIds.forEach((paneId, index) => {
    const row = Math.floor(index / cols);
    const column = index % cols;
    const rowCount = row === lastRowIndex ? count - row * cols : cols;
    const rowWidth = rowCount * cellW + (rowCount - 1) * gap;
    const startX =
      row === lastRowIndex && lastRow === "center" ? margin + (usableW - rowWidth) / 2 : margin;
    rects[paneId] = {
      x: startX + column * (cellW + gap),
      y: margin + row * (cellH + gap),
      width: cellW,
      height: cellH,
    };
  });

  return { rects, reason: `grid-fit ${cols}x${rows}` };
}

registerLayout({
  id: "grid-fit",
  label: "Grid (fit)",
  defaults: DEFAULTS,
  controls: CONTROLS,
  plan: planGridFit,
});
