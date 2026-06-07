import type { PaneId, ViewportBounds, WorldRect } from "../types";

// Declarative param values are intentionally narrow (right-sizing: no nested objects, no DSL).
export type ParamValue = number | boolean | string;
export type LayoutParams = Record<string, ParamValue>;

// The three — and only three — control kinds. The lab auto-renders one input per control.
export interface NumberControl {
  kind: "number";
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
}

export interface ToggleControl {
  kind: "toggle";
  key: string;
  label: string;
}

export interface EnumControl {
  kind: "enum";
  key: string;
  label: string;
  options: ReadonlyArray<{ value: string; label: string }>;
}

export type Control = NumberControl | ToggleControl | EnumControl;

// What a strategy is given. Content-agnostic: pane ids + the world-space layout bounds only.
export interface PlanInput {
  paneIds: readonly PaneId[];
  viewport: ViewportBounds;
  currentRects?: Readonly<Record<PaneId, WorldRect>>;
}

// Strategies return RECTS ONLY. No camera data crosses the seam: the lab computes any fit from
// the committed rect bounding box, so a strategy author never thinks about the camera.
export interface PlanResult {
  rects: Record<PaneId, WorldRect>;
  reason?: string;
}

// P is the strategy's own param shape; the registry stores strategies type-erased to LayoutParams
// (exactly as the viewer registry erases TRef behind canRender). Erasure is made safe by
// validateStrategy at the registerLayout call site.
export interface LayoutStrategy<P extends LayoutParams = LayoutParams> {
  id: string;
  label: string;
  defaults: P;
  controls: readonly Control[];
  plan(input: PlanInput, params: P): PlanResult;
}

// Configs are DATA: a named (strategyId, params) pair. Built-ins are plain literals.
export interface LayoutConfig {
  id: string;
  label: string;
  strategyId: string;
  params: LayoutParams;
}
