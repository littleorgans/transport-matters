import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createCapturedRun, deleteRun } from "../../api";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import type { CliName } from "../../types";

export type CapturedRunKey = string;

export interface CapturedRunRecord {
  provider: CliName;
  runId: string;
}

// Identity of the captured runs lab panes own, keyed by pane instance. Multiple
// panes can run the same provider, and each must attach to its own backend PTY.
// `runs` is persisted so a browser reload re-attaches each pane to its own run
// instead of collapsing same-provider panes onto one shared terminal.
//
// In-flight spawns live in a module map, not in store state: a Promise is not
// serializable, and the dedupe only needs to hold within a session. React 18
// StrictMode mounts effects twice in dev, so two mounts of the same pane can call
// ensureRun before the first POST resolves; sharing by pane key keeps that to a
// single spawn for that pane while same-provider sibling panes stay independent.
const pendingSpawns = new Map<CapturedRunKey, Promise<string>>();

const CAPTURED_RUN_STORAGE_VERSION = 2;

export interface CapturedRunState {
  /** Live run id per captured pane. Persisted so a reload re-attaches instead of re-spawning. */
  runs: Record<CapturedRunKey, CapturedRunRecord>;
  /** Resolve this pane's run id: reuse a persisted/in-flight run, else spawn one. */
  ensureRun(runKey: CapturedRunKey, provider: CliName, cwd?: string): Promise<string>;
  /** Forget and explicitly stop (DELETE) this pane's run. Used on explicit pane close. */
  clearRun(runKey: CapturedRunKey): void;
}

export function createCapturedRunKey(provider: CliName): CapturedRunKey {
  const randomUUID = globalThis.crypto?.randomUUID;
  const uniqueId =
    typeof randomUUID === "function"
      ? randomUUID.call(globalThis.crypto)
      : `${Date.now().toString(36)}:${Math.random().toString(36).slice(2)}`;
  return `${provider}:${uniqueId}`;
}

export const useCapturedRunStore = create<CapturedRunState>()(
  persist(
    (set, get) => ({
      runs: {},

      ensureRun(runKey, provider, cwd) {
        const existing = get().runs[runKey]?.runId;
        if (existing !== undefined) return Promise.resolve(existing);
        const inFlight = pendingSpawns.get(runKey);
        if (inFlight) return inFlight;
        const spawn = createCapturedRun(provider, cwd)
          .then((runId) => {
            pendingSpawns.delete(runKey);
            set((state) => ({ runs: { ...state.runs, [runKey]: { provider, runId } } }));
            return runId;
          })
          .catch((error: unknown) => {
            pendingSpawns.delete(runKey);
            throw error;
          });
        pendingSpawns.set(runKey, spawn);
        return spawn;
      },

      clearRun(runKey) {
        pendingSpawns.delete(runKey);
        const runId = get().runs[runKey]?.runId;
        if (runId === undefined) return;
        set((state) => {
          const { [runKey]: _removed, ...runs } = state.runs;
          return { runs };
        });
        // Best-effort stop: the user is closing the pane, so a failed DELETE must not
        // block the UI. The backend's idle-timeout policy reaps anything that slips by.
        void deleteRun(runId).catch(() => {});
      },
    }),
    {
      name: FRONTEND_STORAGE_KEYS.capturedRunStore,
      storage: createFrontendPersistStorage(),
      version: CAPTURED_RUN_STORAGE_VERSION,
      migrate: (persisted) => {
        const state = persisted as Partial<Pick<CapturedRunState, "runs">>;
        return { runs: state.runs ?? {} };
      },
      partialize: (state) => ({ runs: state.runs }),
    },
  ),
);

export function resetCapturedRunStoreForTests(): void {
  pendingSpawns.clear();
  useCapturedRunStore.setState({ runs: {} });
}
