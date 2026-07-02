import type { Override } from "../../types";

export type OverrideHandler = (batch: Override[]) => void;

export const noopOverride: OverrideHandler = () => {};

export function overrideCountLabel(count: number, readOnly?: boolean): string {
  if (readOnly) return "modified";
  return count === 1 ? "override" : "overrides";
}
