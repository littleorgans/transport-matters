import type { LayoutConfig } from "./types";

// Named presets (DATA). Empty params mean "use the strategy's defaults". A new strategy does NOT
// need an entry here — it appears in the lab picker via listLayouts(); configs are convenience.
export const BUILT_IN_CONFIGS: readonly LayoutConfig[] = [
  { id: "grid-fit-default", label: "Grid (fit)", strategyId: "grid-fit", params: {} },
];
