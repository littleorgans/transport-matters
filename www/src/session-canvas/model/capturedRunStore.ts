import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createCapturedRun, deleteRun } from "../../api";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import type { CliName } from "../../types";

export type CapturedRunKey = string;

export interface CapturedRunRecord {
  provider: CliName;
  runId: string;
  /**
   * True while this run's pane is parked in the dock. Persisted so a browser reload re-docks the run
   * instead of reopening it as an active pane (S2). Absent/false = open. Set when an established run is
   * minimized, or — when a minimize races the in-flight spawn — applied at resolve via a deferred
   * minimize-intent (see minimizedPendingKeys), so a mid-spawn minimize still docks on reload.
   */
  minimized?: boolean;
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

// Keys whose pane was closed while their spawn POST was still in flight. The spawn's
// resolve handler honours this: it stops the just-born run (DELETE) and skips persisting
// it, so a close that races a spawn leaves neither an orphaned server run nor a zombie
// run that a reload would restore.
const cancelledKeys = new Set<CapturedRunKey>();

// Keys minimized while their spawn POST was still in flight (no record to flag yet). The spawn's
// resolve handler honours this: it persists the new record already `minimized`, so a minimize that
// races the spawn still docks on reload instead of reopening. Mirrors cancelledKeys but with the
// opposite intent — cancel = DELETE + drop; minimize = persist WITH the flag. A key is cancelled OR
// minimize-pending, never both: stopRun's cancel path clears this, so cancel always wins the race.
const minimizedPendingKeys = new Set<CapturedRunKey>();

// Bumped 2 -> 3 in S2: records gained the optional `minimized` dock flag. The migrate below is shape
// tolerant, so pre-S2 records (no flag) load clean and reopen as active panes, exactly as in S1.
const CAPTURED_RUN_STORAGE_VERSION = 3;

export interface CapturedRunState {
  /** Live run id per captured pane. Persisted so a reload re-attaches instead of re-spawning. */
  runs: Record<CapturedRunKey, CapturedRunRecord>;
  /** Resolve this pane's run id: reuse a persisted/in-flight run, else spawn one. */
  ensureRun(
    runKey: CapturedRunKey,
    provider: CliName,
    cwd?: string,
    /** Bridge answers the CLI's OSC color queries (default true; spawn-time only). */
    oscColorReplies?: boolean,
  ): Promise<string>;
  /**
   * Stop this pane's run on an explicit KILL ([X] close): forget the mapping AND DELETE the
   * run. A run id that exists is stopped on the server; a close that races an in-flight spawn
   * (no run id yet) is cancelled so the just-born run is DELETEd and never persisted, so an
   * unviewed run never orphans. Minimize, by contrast, keeps the binding (the run lives) so the
   * dock can restore it locally — only close calls this.
   */
  stopRun(runKey: CapturedRunKey): void;
  /**
   * Set/clear this pane's persisted dock flag so a reload re-docks a minimized run (true) or reopens a
   * restored one (false). On an established run it updates the record directly; when a minimize races
   * the in-flight spawn (no record yet) it defers the flag to the spawn's resolve. A genuine no-op
   * only when there is neither a record nor an in-flight spawn.
   */
  setMinimized(runKey: CapturedRunKey, minimized: boolean): void;
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

      ensureRun(runKey, provider, cwd, oscColorReplies = true) {
        const existing = get().runs[runKey]?.runId;
        if (existing !== undefined) return Promise.resolve(existing);
        const inFlight = pendingSpawns.get(runKey);
        if (inFlight) return inFlight;
        // A fresh spawn intent for this key supersedes any stale cancellation or minimize-intent (e.g.
        // a retry after a failed spawn): the user is opening it anew, so it persists open by default.
        cancelledKeys.delete(runKey);
        minimizedPendingKeys.delete(runKey);
        const spawn = createCapturedRun(provider, cwd, oscColorReplies)
          .then((runId) => {
            pendingSpawns.delete(runKey);
            // Closed mid-spawn: stop the just-born run and do NOT persist it. .delete
            // returns true only if the key was marked cancelled (atomic check + clear).
            if (cancelledKeys.delete(runKey)) {
              void deleteRun(runId).catch(() => {});
              return runId;
            }
            // Minimized mid-spawn: persist the record already docked so a reload docks it (not reopen).
            // .delete is the atomic check + clear of the deferred intent.
            const minimized = minimizedPendingKeys.delete(runKey);
            set((state) => ({
              runs: {
                ...state.runs,
                [runKey]: minimized ? { provider, runId, minimized: true } : { provider, runId },
              },
            }));
            return runId;
          })
          .catch((error: unknown) => {
            pendingSpawns.delete(runKey);
            cancelledKeys.delete(runKey);
            minimizedPendingKeys.delete(runKey);
            throw error;
          });
        pendingSpawns.set(runKey, spawn);
        return spawn;
      },

      stopRun(runKey) {
        const runId = get().runs[runKey]?.runId;
        if (runId !== undefined) {
          // Established run: forget this pane's mapping and STOP the run (DELETE). Best-effort
          // stop — the user is killing the pane, so a failed DELETE must not block the UI; the
          // backend idle policy reaps anything that slips by. The stopped run also leaves the
          // director roster (it is no longer a live run).
          set((state) => {
            const { [runKey]: _removed, ...runs } = state.runs;
            return { runs };
          });
          void deleteRun(runId).catch(() => {});
          return;
        }
        // Kill raced an in-flight spawn (no run id yet): cancel so the spawn's resolve stops the
        // just-born run (DELETE) and skips persisting it, so a run that was never viewed or listed
        // can never orphan. The pending promise stays so its handler runs that cleanup. Drop any
        // deferred minimize-intent for this key so close wins the race (cancel, not dock).
        if (pendingSpawns.has(runKey)) {
          cancelledKeys.add(runKey);
          minimizedPendingKeys.delete(runKey);
        }
      },

      setMinimized(runKey, minimized) {
        if (!minimized) {
          // Restore: drop any deferred minimize-intent, then clear the flag on an established record.
          minimizedPendingKeys.delete(runKey);
        } else if (!get().runs[runKey] && pendingSpawns.has(runKey)) {
          // Minimized mid-spawn: no established record yet, so DEFER the flag to the spawn's resolve
          // via an intent (the run is still being born). Without this the minimize would be lost and a
          // reload would reopen instead of dock. cancel still wins if a close also fires (see stopRun).
          minimizedPendingKeys.add(runKey);
          return;
        }
        set((state) => {
          const record = state.runs[runKey];
          if (!record) return {}; // no run and no in-flight spawn: nothing to flag
          return { runs: { ...state.runs, [runKey]: { ...record, minimized } } };
        });
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
  cancelledKeys.clear();
  minimizedPendingKeys.clear();
  useCapturedRunStore.setState({ runs: {} });
}
