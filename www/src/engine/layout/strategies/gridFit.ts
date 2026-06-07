import type { WorldRect } from "../../types";
import { registerLayout } from "../registry";
import type { Control, LayoutParams, PlanInput, PlanResult } from "../types";

// Width-first grid that caps columns by target aspect so high pane counts don't become slivers.
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

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

export function planGridFit(input: PlanInput, params: GridFitParams): PlanResult {
  const { paneIds, viewport } = input;
  const count = paneIds.length;
  if (count === 0) return { rects: {} };

  const { minW, minH, gap, margin, targetAspect, lastRow } = params;
  const usableW = viewport.width - 2 * margin;
  const usableH = viewport.height - 2 * margin;

  // Width capacity is the upper bound on columns (keeps cellW >= minW); the aspect cap picks the
  // actual column count within it so N=4 -> 2x2 and N=12 -> 4x3 instead of one tall-sliver row.
  const capacity = clamp(Math.floor((viewport.width - 2 * margin + gap) / (minW + gap)), 1, count);
  const aspectCols = clamp(
    Math.round(Math.sqrt((viewport.width * count) / (viewport.height * targetAspect))),
    1,
    count,
  );
  const cols = Math.min(capacity, aspectCols);
  const rows = Math.ceil(count / cols);

  let cellW = (usableW - (cols - 1) * gap) / cols;
  let cellH = (usableH - (rows - 1) * gap) / rows;
  if (cellH < minH) cellH = minH; // keep panes readable; the lab fits the camera (Fit to content)
  cellW = Math.max(cellW, minW);

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
