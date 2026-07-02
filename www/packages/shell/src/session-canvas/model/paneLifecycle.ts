import { capturedRunLifecyclePolicy } from "./capturedRunLifecycle";
import type { CanvasPaneRef } from "./paneRecords";

export type PaneLifecycleKind = CanvasPaneRef["kind"];

/**
 * Per-kind lifecycle hooks fed the pane's own content ref. Absent hook = the generic
 * path (dock on minimize, restore on un-dock, remove on close) with no resource side effect. The
 * store runs the resolved hook at the matching transition, replacing the old `kind === ...` branch.
 * `onMinimize`/`onClose` run inside the close-delay window; `onRestore` runs as the pane leaves the
 * dock (captured-run uses the minimize/restore pair to set/clear its persisted dock flag).
 */
export interface PaneLifecyclePolicy<TRef extends CanvasPaneRef = CanvasPaneRef> {
  onMinimize?(ref: TRef): void;
  onRestore?(ref: TRef): void;
  onClose?(ref: TRef): void;
}

/** Static defaults: core owns resource cleanup hooks that every route must see. */
const PANE_LIFECYCLE_POLICIES: Partial<Record<PaneLifecycleKind, PaneLifecyclePolicy>> = {
  "captured-run": capturedRunLifecyclePolicy,
};

/** Runtime overrides for tests and future route-specific policy experiments. */
const overrides: Partial<Record<PaneLifecycleKind, PaneLifecyclePolicy>> = {};

export function registerLifecycle(kind: PaneLifecycleKind, policy: PaneLifecyclePolicy): void {
  overrides[kind] = policy;
}

const EMPTY: PaneLifecyclePolicy = {};

/** Resolve the policy for a ref. A null ref (demo card/ruler stub) is always plain. */
export function resolvePaneLifecycle(ref: CanvasPaneRef | null): PaneLifecyclePolicy {
  if (!ref) return EMPTY;
  return overrides[ref.kind] ?? PANE_LIFECYCLE_POLICIES[ref.kind] ?? EMPTY;
}
