import { lazy, Suspense, useMemo } from "react";
import { selectRootRoute } from "./session-canvas/route";

/**
 * The route fork, extracted from main.tsx so the full page composition is
 * testable. main.tsx stays a dumb entry point (createRoot + window chrome);
 * everything an app surface shares across routes mounts here.
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
const InspectorApp = lazy(() => import("./app").then(({ App }) => ({ default: App })));

const routeComponents = {
  canvas: SessionCanvasRoute,
  "canvas-lab": CanvasLabRoute,
  inspector: InspectorApp,
} as const;

export function RootShell() {
  const route = useMemo(() => selectRootRoute(window.location.pathname), []);
  const RouteComponent = routeComponents[route];
  return (
    <Suspense fallback={<div>Loading Transport Matters</div>}>
      <RouteComponent />
    </Suspense>
  );
}
