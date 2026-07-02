import { useCapturedRunStore } from "./capturedRunStore";
import type { PaneLifecyclePolicy } from "./paneLifecycle";

export const capturedRunLifecyclePolicy: PaneLifecyclePolicy = {
  onMinimize: (ref) => {
    if (ref.kind !== "captured-run") return;
    useCapturedRunStore.getState().setMinimized(ref.runKey, true);
  },
  onRestore: (ref) => {
    if (ref.kind !== "captured-run") return;
    useCapturedRunStore.getState().setMinimized(ref.runKey, false);
  },
  onClose: (ref) => {
    if (ref.kind !== "captured-run") return;
    useCapturedRunStore.getState().stopRun(ref.runKey);
  },
};
