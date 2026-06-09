import { registerLifecycle } from "../model/paneLifecycle";
import { useCapturedRunStore } from "./capturedRunStore";

// Lab-side lifecycle wiring. Imported once by CanvasLabRoute so the side effect runs on mount.
// Keeping it here (not in model/) is what keeps capturedRunStore out of the prod bundle: the
// shared policy table ships empty and the lab augments it on load.
//
// Minimize/restore keep the runKey -> runId binding (the run lives; the viewer WS closes on unmount so
// its viewer count falls, and restore re-seeds the pane so ensureRun re-attaches by the kept id). What
// they add in S2 is persistence: minimize flags the run docked so a reload re-docks it, restore clears
// the flag so a reload after restore reopens it. Close is the only DESTRUCTIVE hook (DELETE + forget),
// which also drops the record (and its flag) entirely.
registerLifecycle("captured-run", {
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
});
