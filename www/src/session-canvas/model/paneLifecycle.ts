import type { CanvasPaneRef } from "./paneRecords";

export type PaneLifecycleKind = CanvasPaneRef["kind"];

/**
 * Per-kind lifecycle hooks fed the pane's own content ref. Absent hook = the generic
 * path (dock on minimize, remove on close) with no resource side effect. The store runs
 * the resolved hook inside the close-delay window, replacing the old `kind === ...` branch.
 */
export interface PaneLifecyclePolicy<TRef extends CanvasPaneRef = CanvasPaneRef> {
  onMinimize?(ref: TRef): void;
  onClose?(ref: TRef): void;
}

/** Static defaults: every kind is plain (no hooks). The lab augments captured-run at runtime. */
const PANE_LIFECYCLE_POLICIES: Partial<Record<PaneLifecycleKind, PaneLifecyclePolicy>> = {};

/** Runtime overrides registered lab-side so capturedRunStore stays out of model/ + prod. */
const overrides: Partial<Record<PaneLifecycleKind, PaneLifecyclePolicy>> = {};

/**
 * Lab-side attach point. Keeps capturedRunStore (the only ref with a close side effect) out of
 * model/ and the prod bundle: model/ ships an empty table, the lab registers its hooks on import.
 */
export function registerLifecycle(kind: PaneLifecycleKind, policy: PaneLifecyclePolicy): void {
  overrides[kind] = policy;
}

const EMPTY: PaneLifecyclePolicy = {};

/** Resolve the policy for a ref. A null ref (demo card/ruler stub) is always plain. */
export function resolvePaneLifecycle(ref: CanvasPaneRef | null): PaneLifecyclePolicy {
  if (!ref) return EMPTY;
  return overrides[ref.kind] ?? PANE_LIFECYCLE_POLICIES[ref.kind] ?? EMPTY;
}
