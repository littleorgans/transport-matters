import { useEffect, useMemo, useState } from "react";
import { getRun, type RunView } from "../api";
import { useMeta } from "../hooks/useMeta";
import { KeybindingEngineProvider } from "../keybindings/engine";
import { CanvasSurface } from "./components/CanvasSurface";
import { useLaunchSession } from "./hooks/useLaunchSession";
import { useCanvasStore } from "./model/canvasStore";
import { type CapturedRunKey, useCapturedRunStore } from "./model/capturedRunStore";
import { SessionCanvasStressRoute } from "./perf/SessionCanvasStressRoute";
import { isStressCanvas, parseCanvasLaunchContext } from "./route";

type CapturedRunReconciliation = "pending" | "released";
const CAPTURED_RUN_RECONCILIATION_TIMEOUT_MS = 3_000;

export function SessionCanvasRoute() {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const launch = useMemo(() => parseCanvasLaunchContext(search), [search]);
  const stress = useMemo(() => isStressCanvas(search), [search]);
  const initializeCanvas = useCanvasStore((state) => state.initializeCanvas);
  const adoptDefaultWorktree = useCanvasStore((state) => state.adoptDefaultWorktree);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
  const { meta } = useMeta();
  const [capturedRunReconciliation, setCapturedRunReconciliation] =
    useState<CapturedRunReconciliation>(() =>
      hasRememberedCapturedRuns() ? "pending" : "released",
    );
  const launchResolution = useLaunchSession(launch);
  const resolved =
    launchResolution.data?.status === "resolved" ? launchResolution.data.session : undefined;
  const hasLaunchLookup = launch.workspaceHash !== null && launch.harness !== null;
  const launchStatus =
    launchResolution.data?.status ??
    (hasLaunchLookup && launchResolution.isPending ? "pending" : "unavailable");

  useEffect(() => {
    initializeCanvas(launch);
  }, [initializeCanvas, launch]);

  // The desktop default launch carries no worktree in its URL, so seed the canvas
  // default spawn target from the backend's resolved launch worktree (meta). An
  // explicit URL worktree (worktree switch) owns the default and is left alone.
  useEffect(() => {
    if (launch.worktreeId !== null) return;
    if (!meta?.worktreeId) return;
    adoptDefaultWorktree(meta.spaceId, meta.worktreeId);
  }, [launch.worktreeId, meta?.spaceId, meta?.worktreeId, adoptDefaultWorktree]);

  useEffect(() => {
    if (resolved) spawnOrFocusTranscript(resolved);
  }, [resolved, spawnOrFocusTranscript]);

  useEffect(() => {
    if (capturedRunReconciliation !== "pending") return;
    let cancelled = false;
    const pruneCandidates = snapshotCapturedRunPruneCandidates();

    reconcileCapturedRuns(pruneCandidates)
      .then((staleRunKeys) => {
        if (cancelled) return;
        for (const runKey of staleRunKeys) {
          useCapturedRunStore.getState().dropRun(runKey);
          useCanvasStore.getState().dropCapturedRunPane(runKey);
        }
      })
      .catch(() => {
        // Transient lookup failures must not delete local run or pane state. The
        // next route mount will re-enter reconciliation from the persisted ids.
      })
      .finally(() => {
        if (!cancelled) setCapturedRunReconciliation("released");
      });

    return () => {
      cancelled = true;
    };
  }, [capturedRunReconciliation]);

  if (stress) return <SessionCanvasStressRoute />;

  return (
    <KeybindingEngineProvider>
      <CanvasSurface
        capturedRunsReady={capturedRunReconciliation === "released"}
        launch={launch}
        launchSessionId={resolved?.sessionId ?? null}
        launchStatus={launchStatus}
      />
    </KeybindingEngineProvider>
  );
}

function hasRememberedCapturedRuns(): boolean {
  return Object.keys(useCapturedRunStore.getState().runs).length > 0;
}

function snapshotCapturedRunPruneCandidates(): Map<CapturedRunKey, string> {
  return new Map(
    Object.entries(useCapturedRunStore.getState().runs).map(([runKey, record]) => [
      runKey,
      record.runId,
    ]),
  );
}

async function reconcileCapturedRuns(
  pruneCandidates: Map<CapturedRunKey, string>,
): Promise<CapturedRunKey[]> {
  if (pruneCandidates.size === 0) return [];
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      controller.abort();
      reject(new Error("captured run reconciliation timed out"));
    }, CAPTURED_RUN_RECONCILIATION_TIMEOUT_MS);
  });
  return Promise.race([
    findStaleCapturedRunKeys(pruneCandidates, controller.signal),
    timeout,
  ]).finally(() => {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  });
}

async function findStaleCapturedRunKeys(
  pruneCandidates: Map<CapturedRunKey, string>,
  signal: AbortSignal,
): Promise<CapturedRunKey[]> {
  const lookups = await Promise.all(
    [...pruneCandidates].map(async ([runKey, runId]) => ({
      run: await getRun(runId, { signal }),
      runKey,
    })),
  );
  return lookups.filter(({ run }) => !isAttachableRun(run)).map(({ runKey }) => runKey);
}

function isAttachableRun(run: RunView | null): boolean {
  return run?.state === "STARTING" || run?.state === "RUNNING";
}
