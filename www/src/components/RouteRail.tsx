import type { Route } from "../stores/uiStore";
import { useUIStore } from "../stores/uiStore";

/**
 * Top-level route rail: INTERCEPT / OVERLAYS / TRACE / RECALL.
 *
 * Four lenses on the same exchange stream. Active route is a pressed well
 * (reuses .tab-pressed from the editor's FORM/RAW bar), rest routes sit on
 * the raised surface. The pressed-key metaphor is deliberately the same as
 * the nested FORM/RAW switcher — a route is a "bigger tab".
 *
 * Each tab carries a keyboard hint (1/2/3/4). Tabs without a functional
 * view yet (TRACE, RECALL) wear a muted SOON marker so users know the
 * route is scaffolded, not broken. OVERLAYS is functional in this slice,
 * so it wears no SOON marker.
 */

interface RouteDef {
  id: Route;
  label: string;
  available: boolean;
  /** Accent color class used on the SOON marker, matching the route's own view. */
  soonClass: string;
}

const ROUTES: readonly RouteDef[] = [
  { id: "intercept", label: "Intercept", available: true, soonClass: "" },
  { id: "overlays", label: "Overlays", available: true, soonClass: "" },
  { id: "trace", label: "Trace", available: false, soonClass: "text-lavender" },
  { id: "recall", label: "Recall", available: false, soonClass: "text-sky" },
] as const;

export function RouteRail() {
  const activeRoute = useUIStore((s) => s.activeRoute);
  const setActiveRoute = useUIStore((s) => s.setActiveRoute);

  return (
    <div className="flex border-b border-edge">
      {ROUTES.map((route, idx) => {
        const isActive = activeRoute === route.id;
        return (
          <button
            key={route.id}
            type="button"
            onClick={() => setActiveRoute(route.id)}
            aria-current={isActive ? "page" : undefined}
            className={[
              "group relative flex items-center gap-3 px-6 py-3 cursor-pointer",
              "text-[12px] font-medium uppercase tracking-[0.18em] transition-all duration-150",
              idx > 0 ? "border-l border-edge" : "",
              isActive ? "tab-pressed text-txt" : "tab-rest text-txt-3 hover:text-txt-2",
            ].join(" ")}
          >
            <span>{route.label}</span>
            {!route.available && (
              <span
                title="Not available yet"
                className={[
                  "hidden md:inline text-[9px] tracking-[0.22em]",
                  route.soonClass,
                  isActive ? "" : "opacity-60 group-hover:opacity-100",
                ].join(" ")}
              >
                SOON
              </span>
            )}
          </button>
        );
      })}
      <div className="flex-1 tab-rest" />
    </div>
  );
}
