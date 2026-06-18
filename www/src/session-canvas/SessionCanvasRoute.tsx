import { useEffect, useMemo } from "react";
import { CanvasSurface } from "./components/CanvasSurface";
import { useLaunchSession } from "./hooks/useLaunchSession";
import { useCanvasStore } from "./model/canvasStore";
import { SessionCanvasStressRoute } from "./perf/SessionCanvasStressRoute";
import { isStressCanvas, parseCanvasLaunchContext } from "./route";

export function SessionCanvasRoute() {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const launch = useMemo(() => parseCanvasLaunchContext(search), [search]);
  const stress = useMemo(() => isStressCanvas(search), [search]);
  const initializeCanvas = useCanvasStore((state) => state.initializeCanvas);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
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

  if (stress) return <SessionCanvasStressRoute />;

  return (
    <CanvasSurface
      launch={launch}
      launchSessionId={resolved?.sessionId ?? null}
      launchStatus={launchStatus}
    />
  );
}
