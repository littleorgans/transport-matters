// Shared in-app navigation between canvas surfaces. Mounted in BOTH command bars
// (CanvasCommandBar for /canvas and CanvasLabRoute for /canvas-lab) — one component, two sites.
// Routes are data so adding a surface later is a one-line edit (registry ethos).

export interface CanvasRoute {
  id: string;
  label: string;
  path: string;
}

export const CANVAS_ROUTES: readonly CanvasRoute[] = [
  { id: "canvas", label: "Canvas", path: "/canvas" },
  { id: "canvas-lab", label: "Lab", path: "/canvas-lab" },
];

export interface RouteSwitcherProps {
  routes?: readonly CanvasRoute[];
}

export function RouteSwitcher({ routes = CANVAS_ROUTES }: RouteSwitcherProps) {
  const current = typeof window === "undefined" ? "" : window.location.pathname;
  return (
    <nav aria-label="Canvas surfaces" className="canvas-route-switcher">
      {routes.map((route) => {
        const active = route.path === current;
        return (
          <button
            aria-current={active ? "page" : undefined}
            className="canvas-button canvas-route-switcher__link"
            data-active={active}
            key={route.id}
            onClick={() => navigateToRoute(route.path)}
            type="button"
          >
            {route.label}
          </button>
        );
      })}
    </nav>
  );
}

// Full-load navigation to the target pathname, PRESERVING the current query string so returning to
// /canvas keeps its workspace_hash / cli / run_id launch context (www has no client router).
function navigateToRoute(path: string): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === path) return;
  window.location.assign(`${path}${window.location.search}`);
}
