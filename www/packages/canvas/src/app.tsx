import { lazy, Suspense, useMemo } from "react";

/**
 * The canvas bundle's route fork. The API serves this bundle at /canvas and
 * for the /canvas-lab page (RouteSwitcher and the launcher navigate between
 * the two); every other path belongs to the inspector bundle. Lazy imports
 * keep the lab chunk off the /canvas critical path, mirroring the dev shell.
 */
const SessionCanvasRoute = lazy(() =>
  import("./session-canvas/SessionCanvasRoute").then(({ SessionCanvasRoute }) => ({
    default: SessionCanvasRoute,
  })),
);
const CanvasLabRoute = lazy(() =>
  import("./session-canvas/lab/CanvasLabRoute").then(({ CanvasLabRoute }) => ({
    default: CanvasLabRoute,
  })),
);

export function selectCanvasRoute(pathname: string): "canvas" | "canvas-lab" {
  return pathname === "/canvas-lab" ? "canvas-lab" : "canvas";
}

export function CanvasApp() {
  const route = useMemo(() => selectCanvasRoute(window.location.pathname), []);
  const RouteComponent = route === "canvas-lab" ? CanvasLabRoute : SessionCanvasRoute;
  return (
    <Suspense fallback={<div>Loading Transport Matters</div>}>
      <RouteComponent />
    </Suspense>
  );
}
