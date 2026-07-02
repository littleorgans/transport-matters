import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { fetchMeta } from "./api";
import "./index.css";
import "./index.launcher.css";
import "./session-canvas/canvas.css";
import "./session-canvas/viewers/placeholder/placeholder-pane.css";
import { mountWindowChrome } from "@/host/mountWindowChrome";
import { queryClient } from "./lib/queryClient";
import { RootShell } from "./rootShell";
import { selectRootRoute } from "./session-canvas/route";

// Warm the meta cache before the first render so OverlaysView can
// stamp real cwds onto project-scoped drafts the moment a user saves.
// Fire-and-forget: the hook uses Number.POSITIVE_INFINITY staleTime, so
// even if this races the first paint, the in-flight promise is
// deduplicated by the query client.
if (selectRootRoute(window.location.pathname) === "inspector") {
  queryClient.prefetchQuery({ queryKey: ["meta"], queryFn: () => fetchMeta() });
}

// Host chrome, not app UI: mounted before #root so the drag strip stays beneath app
// hit-testing by DOM order while the pointer-inert channel badge can paint above both.
mountWindowChrome();

// biome-ignore lint/style/noNonNullAssertion: The entry point exists
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RootShell />
    </QueryClientProvider>
  </StrictMode>,
);
