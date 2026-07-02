import type { PaneId, ViewportBounds, WorldRect } from "../types";

// Single source of truth for the pane-grid top/edge margin in world units. Shared by every layout
// strategy (grid-fit, single-row) and the production planner so the three never drift, and surfaced
// to CSS as --canvas-layout-margin so the dock band height reads the same number. The lab strategies
// expose it as a tunable `margin` slider default; this is that default, not a hard floor.
export const CANVAS_LAYOUT_MARGIN = 64;

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

// Strategies return RECTS, plus an optional `frame`: the world rectangle the lab should fit the
// camera to. No camera TRANSFORM crosses the seam (a strategy author never computes scale/pan); a
// `frame` is still just geometry. It lets a strategy declare breathing room (e.g. grid-fit pads its
// grid by `margin`) so the fit honors it. When omitted, the lab falls back to the rect bounding box.
export interface PlanResult {
  rects: Record<PaneId, WorldRect>;
  reason?: string;
  frame?: WorldRect;
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
