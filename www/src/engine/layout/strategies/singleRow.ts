import type { WorldRect } from "../../types";
import { registerLayout } from "../registry";
import type { Control, LayoutParams, PlanInput, PlanResult } from "../types";

// Extensibility proof (spec §6): this whole file is the ONLY edit needed to add a layout. The
// import.meta.glob auto-loader discovers it, registerLayout publishes it, and the lab picker +
// auto-rendered controls pick it up with zero other edits.
interface SingleRowParams extends LayoutParams {
  minW: number;
  gap: number;
  margin: number;
}

const DEFAULTS: SingleRowParams = { minW: 320, gap: 24, margin: 48 };

const CONTROLS: readonly Control[] = [
  { kind: "number", key: "minW", label: "Min width", min: 120, max: 640, step: 20 },
  { kind: "number", key: "gap", label: "Gap", min: 0, max: 64, step: 4 },
  { kind: "number", key: "margin", label: "Margin", min: 0, max: 120, step: 4 },
];

export function planSingleRow(input: PlanInput, params: SingleRowParams): PlanResult {
  const { paneIds, viewport } = input;
  const count = paneIds.length;
  if (count === 0) return { rects: {} };

  const { minW, gap, margin } = params;
  const width = Math.max(minW, (viewport.width - 2 * margin - (count - 1) * gap) / count);
  const height = viewport.height - 2 * margin;

  const rects: Record<string, WorldRect> = {};
  paneIds.forEach((paneId, index) => {
    rects[paneId] = { x: margin + index * (width + gap), y: margin, width, height };
  });

  return { rects, reason: "single-row" };
}

registerLayout({
  id: "single-row",
  label: "Single row",
  defaults: DEFAULTS,
  controls: CONTROLS,
  plan: planSingleRow,
});
