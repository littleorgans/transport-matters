import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { fetchMeta } from "./api";
import "./index.css";
import "./session-canvas/canvas.css";
import "./session-canvas/viewers/placeholder/placeholder-pane.css";
import { WindowDragRegion } from "./components/WindowDragRegion";
import { queryClient } from "./lib/queryClient";
import { selectRootRoute } from "./session-canvas/route";

const selectedRoute = selectRootRoute(window.location.pathname);
const RootApp = lazy(() => {
  if (selectedRoute === "canvas") {
    return import("./session-canvas/SessionCanvasRoute").then(({ SessionCanvasRoute }) => ({
      default: SessionCanvasRoute,
    }));
  }
  if (selectedRoute === "canvas-lab") {
    return import("./session-canvas/lab/CanvasLabRoute").then(({ CanvasLabRoute }) => ({
      default: CanvasLabRoute,
    }));
  }
  return import("./app").then(({ App }) => ({ default: App }));
});

// Warm the meta cache before the first render so OverlaysView can
// stamp real cwds onto project-scoped drafts the moment a user saves.
// Fire-and-forget: the hook uses Number.POSITIVE_INFINITY staleTime, so
// even if this races the first paint, the in-flight promise is
// deduplicated by the query client.
if (selectedRoute === "legacy") {
  queryClient.prefetchQuery({ queryKey: ["meta"], queryFn: fetchMeta });
}

// Window chrome, not app UI: the drag strip mounts in its own host BEFORE #root, so every
// app surface out-hit-tests it by plain DOM order and no app element ever needs a z-index
// to clear it. Its only job is feeding the OS app-region map, which ignores paint order.
const windowChromeHost = document.createElement("div");
document.body.prepend(windowChromeHost);
createRoot(windowChromeHost).render(
  <StrictMode>
    <WindowDragRegion />
  </StrictMode>,
);

// biome-ignore lint/style/noNonNullAssertion: The entry point exists
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Suspense
        fallback={<div className="min-h-screen bg-canvas text-txt">Loading Transport Matters</div>}
      >
        <RootApp />
      </Suspense>
    </QueryClientProvider>
  </StrictMode>,
);
