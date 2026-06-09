import { registerLifecycle } from "../model/paneLifecycle";
import { useCapturedRunStore } from "./capturedRunStore";

// Lab-side lifecycle wiring. Imported once by CanvasLabRoute so the side effect runs on mount.
// Keeping it here (not in model/) is what keeps capturedRunStore out of the prod bundle: the
// shared policy table ships empty and the lab augments it on load.
//
// Only CLOSE carries a side effect. Minimize keeps the runKey -> runId binding (the run lives, the
// viewer WS closes on unmount so its viewer count falls); restore re-seeds the pane and ensureRun
// re-attaches by the kept id. Close kills the run (DELETE + forget).
registerLifecycle("captured-run", {
  onClose: (ref) => {
    if (ref.kind !== "captured-run") return;
    useCapturedRunStore.getState().stopRun(ref.runKey);
  },
});
