import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createCapturedRun, terminateRun } from "../../api";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import type { HarnessName } from "../../types";

export type CapturedRunKey = string;

export interface CapturedRunRecord {
  provider: HarnessName;
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

export const CAPTURED_RUN_SPAWN_CONCURRENCY = 5;

let activeCapturedRunSpawns = 0;
let queuedCapturedRunSpawnSlots: Array<() => void> = [];

function withCapturedRunSpawnSlot(task: () => Promise<string>): Promise<string> {
  return acquireCapturedRunSpawnSlot().then(async () => {
    try {
      return await task();
    } finally {
      releaseCapturedRunSpawnSlot();
    }
  });
}

function acquireCapturedRunSpawnSlot(): Promise<void> {
  if (activeCapturedRunSpawns < CAPTURED_RUN_SPAWN_CONCURRENCY) {
    activeCapturedRunSpawns += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    queuedCapturedRunSpawnSlots.push(() => {
      activeCapturedRunSpawns += 1;
      resolve();
    });
  });
}

function releaseCapturedRunSpawnSlot(): void {
  activeCapturedRunSpawns -= 1;
  const next = queuedCapturedRunSpawnSlots.shift();
  if (next) next();
}

// Keys whose pane was closed while their spawn POST was still in flight. The spawn's
// resolve handler honours this: it terminates the just-born run (POST /terminate) and skips persisting
// it, so a close that races a spawn leaves neither an orphaned server run nor a zombie
// run that a reload would restore.
const cancelledKeys = new Set<CapturedRunKey>();

// Keys minimized while their spawn POST was still in flight (no record to flag yet). The spawn's
// resolve handler honours this: it persists the new record already `minimized`, so a minimize that
// races the spawn still docks on reload instead of reopening. Mirrors cancelledKeys but with the
// opposite intent: cancel = POST /terminate + drop; minimize = persist WITH the flag. A key is cancelled OR
// minimize-pending, never both: stopRun's cancel path clears this, so cancel always wins the race.
const minimizedPendingKeys = new Set<CapturedRunKey>();

// Bumped 3 -> 4 in Slice 2: the OSC color replies toggle moved from lab state into core.
// The migrate below is shape tolerant, so older records load with the default-on bridge.
const CAPTURED_RUN_STORAGE_VERSION = 4;

export interface CapturedRunState {
  /** Live run id per captured pane. Persisted so a reload re-attaches instead of re-spawning. */
  runs: Record<CapturedRunKey, CapturedRunRecord>;
  /**
   * Bridge answers the harness OSC 10/11 color queries at spawn (backend osc_color_responder), so
   * terminal background-sensitive styling renders deterministically. Spawn-time only.
   */
  oscColorReplies: boolean;
  /** Bypass all permission checks: spawned agents skip permission prompts. Spawn-time only. */
  bypassPermissions: boolean;
  /** Resolve this pane's run id: reuse a persisted/in-flight run, else spawn one. */
  ensureRun(
    runKey: CapturedRunKey,
    provider: HarnessName,
    cwd?: string,
    /** Bridge answers the harness OSC color queries (default true; spawn-time only). */
    oscColorReplies?: boolean,
    /** Named runtime template to launch under (spawn-time only; absent → NATIVE). */
    runtimeTemplate?: string,
  ): Promise<string>;
  /**
   * Stop this pane's run on an explicit KILL ([X] close): forget the mapping AND POST /terminate the
   * run. A run id that exists is terminated on the server; a close that races an in-flight spawn
   * (no run id yet) is cancelled so the just-born run is terminated and never persisted, so an
   * unviewed run never orphans. Minimize, by contrast, keeps the binding (the run lives) so the
   * dock can restore it locally — only close calls this.
   */
  stopRun(runKey: CapturedRunKey): void;
  /**
   * Forget a stale remembered run id without terminating anything server-side.
   * Used when a fresh backend reports that a process-resident run no longer
   * exists, so there is nothing safe or useful to POST /terminate.
   */
  dropRun(runKey: CapturedRunKey): void;
  /**
   * Set/clear this pane's persisted dock flag so a reload re-docks a minimized run (true) or reopens a
   * restored one (false). On an established run it updates the record directly; when a minimize races
   * the in-flight spawn (no record yet) it defers the flag to the spawn's resolve. A genuine no-op
   * only when there is neither a record nor an in-flight spawn.
   */
  setMinimized(runKey: CapturedRunKey, minimized: boolean): void;
  setOscColorReplies(on: boolean): void;
  /** Flip the persisted bypass-permissions flag in place (mirrors the Settings → toggle). */
  toggleBypassPermissions(): void;
}

export function createCapturedRunKey(provider: HarnessName): CapturedRunKey {
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
      oscColorReplies: true,
      bypassPermissions: false,

      ensureRun(runKey, provider, cwd, oscColorReplies = get().oscColorReplies, runtimeTemplate) {
        const existing = get().runs[runKey]?.runId;
        if (existing !== undefined) return Promise.resolve(existing);
        const inFlight = pendingSpawns.get(runKey);
        if (inFlight) return inFlight;
        // A fresh spawn intent for this key supersedes any stale cancellation or minimize-intent (e.g.
        // a retry after a failed spawn): the user is opening it anew, so it persists open by default.
        cancelledKeys.delete(runKey);
        minimizedPendingKeys.delete(runKey);
        const spawn = withCapturedRunSpawnSlot(() =>
          createCapturedRun(
            provider,
            cwd,
            oscColorReplies,
            runtimeTemplate,
            get().bypassPermissions,
          ),
        )
          .then((runId) => {
            pendingSpawns.delete(runKey);
            // Closed mid-spawn: terminate the just-born run and do NOT persist it. .delete
            // returns true only if the key was marked cancelled (atomic check + clear).
            if (cancelledKeys.delete(runKey)) {
              void terminateRun(runId).catch(() => {});
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
          // Established run: forget this pane's mapping and terminate the run (POST /terminate). Best-effort
          // terminate, the user is killing the pane, so a failed POST /terminate must not block the UI; the
          // backend idle policy reaps anything that slips by. The terminated run also leaves the
          // director roster (it is no longer a live run).
          set((state) => {
            const { [runKey]: _removed, ...runs } = state.runs;
            return { runs };
          });
          void terminateRun(runId).catch(() => {});
          return;
        }
        // Kill raced an in-flight spawn (no run id yet): cancel so the spawn's resolve stops the
        // just-born run (POST /terminate) and skips persisting it, so a run that was never viewed or listed
        // can never orphan. The pending promise stays so its handler runs that cleanup. Drop any
        // deferred minimize-intent for this key so close wins the race (cancel, not dock).
        if (pendingSpawns.has(runKey)) {
          cancelledKeys.add(runKey);
          minimizedPendingKeys.delete(runKey);
        }
      },

      dropRun(runKey) {
        cancelledKeys.delete(runKey);
        minimizedPendingKeys.delete(runKey);
        set((state) => {
          if (!state.runs[runKey]) return {};
          const { [runKey]: _removed, ...runs } = state.runs;
          return { runs };
        });
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

      setOscColorReplies(on) {
        set({ oscColorReplies: on });
      },

      toggleBypassPermissions() {
        set((state) => ({ bypassPermissions: !state.bypassPermissions }));
      },
    }),
    {
      name: FRONTEND_STORAGE_KEYS.capturedRunStore,
      storage: createFrontendPersistStorage(),
      version: CAPTURED_RUN_STORAGE_VERSION,
      migrate: (persisted) => {
        const state = persisted as Partial<
          Pick<CapturedRunState, "runs" | "oscColorReplies" | "bypassPermissions">
        >;
        return {
          runs: state.runs ?? {},
          oscColorReplies: state.oscColorReplies !== false,
          // Default OFF: only a stored `true` re-arms the bypass after a reload.
          bypassPermissions: state.bypassPermissions === true,
        };
      },
      partialize: (state) => ({
        runs: state.runs,
        oscColorReplies: state.oscColorReplies,
        bypassPermissions: state.bypassPermissions,
      }),
    },
  ),
);

export function resetCapturedRunStoreForTests(): void {
  pendingSpawns.clear();
  cancelledKeys.clear();
  minimizedPendingKeys.clear();
  activeCapturedRunSpawns = 0;
  queuedCapturedRunSpawnSlots = [];
  useCapturedRunStore.setState({ runs: {}, oscColorReplies: true, bypassPermissions: false });
}
