import { useEffect, useMemo, useState } from "react";
import { listRuns } from "../api";
import { KeybindingEngineProvider } from "../keybindings/engine";
import { CanvasSurface } from "./components/CanvasSurface";
import { useLaunchSession } from "./hooks/useLaunchSession";
import { useCanvasStore } from "./model/canvasStore";
import { type CapturedRunKey, useCapturedRunStore } from "./model/capturedRunStore";
import { SessionCanvasStressRoute } from "./perf/SessionCanvasStressRoute";
import { isStressCanvas, parseCanvasLaunchContext } from "./route";

type CapturedRunReconciliation = "pending" | "released";

export function SessionCanvasRoute() {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const launch = useMemo(() => parseCanvasLaunchContext(search), [search]);
  const stress = useMemo(() => isStressCanvas(search), [search]);
  const initializeCanvas = useCanvasStore((state) => state.initializeCanvas);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
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

  useEffect(() => {
    if (resolved) spawnOrFocusTranscript(resolved);
  }, [resolved, spawnOrFocusTranscript]);

  useEffect(() => {
    if (capturedRunReconciliation !== "pending") return;
    let cancelled = false;
    const pruneCandidates = snapshotCapturedRunPruneCandidates();

    listRuns()
      .then((runs) => {
        if (cancelled) return;
        const liveRunIds = new Set(runs.map((run) => run.runId));
        for (const [runKey, runId] of pruneCandidates) {
          if (liveRunIds.has(runId)) continue;
          useCapturedRunStore.getState().dropRun(runKey);
          useCanvasStore.getState().dropCapturedRunPane(runKey);
        }
      })
      .catch(() => {
        // Transient list failures must not delete local run or pane state. The
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
