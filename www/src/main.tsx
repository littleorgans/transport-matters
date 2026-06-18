import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { fetchMeta } from "./api";
import "./index.css";
import "./index.launcher.css";
import "./session-canvas/canvas.css";
import "./session-canvas/viewers/placeholder/placeholder-pane.css";
import { WindowDragRegion } from "./components/WindowDragRegion";
import { queryClient } from "./lib/queryClient";
import { RootShell } from "./rootShell";
import { selectRootRoute } from "./session-canvas/route";

// Warm the meta cache before the first render so OverlaysView can
// stamp real cwds onto project-scoped drafts the moment a user saves.
// Fire-and-forget: the hook uses Number.POSITIVE_INFINITY staleTime, so
// even if this races the first paint, the in-flight promise is
// deduplicated by the query client.
if (selectRootRoute(window.location.pathname) === "legacy") {
  queryClient.prefetchQuery({ queryKey: ["meta"], queryFn: () => fetchMeta() });
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
      <RootShell />
    </QueryClientProvider>
  </StrictMode>,
);
