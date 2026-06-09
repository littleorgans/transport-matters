import { create } from "zustand";
import { fetchCapabilities } from "../../api";
import type { CliCapability, CliName } from "../../types";

// Single source of managed-CLI install state for the lab. The capability probe
// (GET /api/capabilities) is stable for a process lifetime, so this store fetches
// it exactly once and every consumer (the Spawn Claude / Spawn Codex buttons)
// reads the same result. DRY: one fetch, one cache, no per-button requests.

type CapabilitiesStatus = "idle" | "loading" | "ready" | "error";

export interface CapabilitiesState {
  status: CapabilitiesStatus;
  /** Per-CLI install state once the probe lands; null until the first successful fetch. */
  clis: Record<CliName, CliCapability> | null;
  /** Fetch capabilities exactly once; a no-op while loading, loaded, or already failed. */
  ensureLoaded(): void;
}

export const useCapabilitiesStore = create<CapabilitiesState>()((set, get) => ({
  status: "idle",
  clis: null,
  ensureLoaded() {
    if (get().status !== "idle") return; // fetch once per process
    set({ status: "loading" });
    fetchCapabilities().then(
      (response) => set({ status: "ready", clis: response.clis }),
      () => set({ status: "error" }),
    );
  },
}));

/**
 * Whether a managed CLI is installed. False until a successful probe confirms it,
 * so a button gated on this stays hidden while loading or on error rather than
 * offering a launch that would fail.
 */
export function cliInstalled(state: CapabilitiesState, provider: CliName): boolean {
  return state.clis?.[provider]?.installed ?? false;
}

export function resetCapabilitiesStoreForTests(): void {
  useCapabilitiesStore.setState({ status: "idle", clis: null });
}
