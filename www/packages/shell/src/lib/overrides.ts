import type { Override, OverrideKind } from "../types";

/** Find an override by kind and target, returning its typed value or undefined. */
export function overrideValue<T extends string | boolean | number>(
  overrides: Override[],
  kind: OverrideKind,
  target: string,
): T | undefined {
  const o = overrides.find((ov) => ov.kind === kind && ov.target === target);
  if (o != null && o.value != null) return o.value as T;
  return undefined;
}

/** Check whether any override of the given kind and target exists. */
export function hasOverride(overrides: Override[], kind: OverrideKind, target: string): boolean {
  return overrides.some((o) => o.kind === kind && o.target === target);
}
