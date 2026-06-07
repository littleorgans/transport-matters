import type { LayoutParams, LayoutStrategy } from "./types";

const registry: LayoutStrategy[] = [];

const KIND_TYPE = { number: "number", toggle: "boolean", enum: "string" } as const;

// Dev-time guard so the type-erased registry is SAFE: every control.key must exist in defaults,
// its kind must match the default's runtime type, and an enum default must be one of its options.
// Throws like resolveViewer — caught at the strategy's first import, never silently at setParam.
export function validateStrategy<P extends LayoutParams>(strategy: LayoutStrategy<P>): void {
  for (const control of strategy.controls) {
    if (!(control.key in strategy.defaults)) {
      throw new Error(`[${strategy.id}] control "${control.key}" is not in defaults`);
    }
    const actual = typeof strategy.defaults[control.key];
    if (actual !== KIND_TYPE[control.kind]) {
      throw new Error(
        `[${strategy.id}] control "${control.key}" is ${control.kind} but its default is ${actual}`,
      );
    }
    if (
      control.kind === "enum" &&
      !control.options.some((option) => option.value === strategy.defaults[control.key])
    ) {
      throw new Error(
        `[${strategy.id}] enum default "${String(strategy.defaults[control.key])}" is not in options`,
      );
    }
  }
}

export function registerLayout<P extends LayoutParams>(strategy: LayoutStrategy<P>): void {
  validateStrategy(strategy);
  const erased = strategy as unknown as LayoutStrategy;
  const index = registry.findIndex((entry) => entry.id === erased.id);
  if (index >= 0)
    registry[index] = erased; // upsert (same semantics as registerViewer)
  else registry.push(erased);
}

export function listLayouts(): readonly LayoutStrategy[] {
  return registry;
}

export function resolveLayout(strategyId: string): LayoutStrategy {
  const strategy = registry.find((entry) => entry.id === strategyId);
  if (!strategy) throw new Error(`No layout strategy registered for "${strategyId}".`);
  return strategy;
}
