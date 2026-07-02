import { fetchCapabilities } from "@tm/core";
import type { HarnessCapability, HarnessName } from "@tm/core/types/capabilities";
import { create } from "zustand";

// Single source of managed harness install state for the lab. The capability probe
// (GET /api/capabilities) is stable for a process lifetime, so this store fetches
// it exactly once and every consumer (the Spawn Claude / Spawn Codex buttons)
// reads the same result. DRY: one fetch, one cache, no per-button requests.

type CapabilitiesStatus = "idle" | "loading" | "ready" | "error";

export interface CapabilitiesState {
  status: CapabilitiesStatus;
  /** Per-harness install state once the probe lands; null until the first successful fetch. */
  harnesses: Record<HarnessName, HarnessCapability> | null;
  /** Fetch capabilities exactly once; a no-op while loading, loaded, or already failed. */
  ensureLoaded(): void;
}

export const useCapabilitiesStore = create<CapabilitiesState>()((set, get) => ({
  status: "idle",
  harnesses: null,
  ensureLoaded() {
    if (get().status !== "idle") return; // fetch once per process
    set({ status: "loading" });
    fetchCapabilities().then(
      (response) => set({ status: "ready", harnesses: response.harnesses }),
      () => set({ status: "error" }),
    );
  },
}));

/**
 * Whether a managed harness is available to spawn. Fail-open: only a successful probe
 * that CONFIRMS `installed === false` hides the button. While the probe is idle,
 * in-flight, or failed (`harnesses` null — e.g. a dev server with no backend), default
 * to available so the control never silently vanishes just because the probe could
 * not run. `??` only defaults on null/undefined, so a real `false` still hides.
 */
export function harnessInstalled(state: CapabilitiesState, provider: HarnessName): boolean {
  return state.harnesses?.[provider]?.installed ?? true;
}

export function resetCapabilitiesStoreForTests(): void {
  useCapabilitiesStore.setState({ status: "idle", harnesses: null });
}
