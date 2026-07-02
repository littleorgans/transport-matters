import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@tm/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "@tm/host/styles.css";
import { mountWindowChrome } from "@tm/host";
import { CanvasApp } from "./app";
import { bootstrapThemeTokens } from "./hooks/useThemeTokens";

// Host chrome, not app UI: mounted before #root so the drag strip stays beneath app
// hit-testing by DOM order while the pointer-inert channel badge can paint above both.
mountWindowChrome();

// Apply the persisted theme (or clear stale inline tokens) before the first
// paint; the routes keep useThemeTokens() mounted for live theme switching.
bootstrapThemeTokens();

// biome-ignore lint/style/noNonNullAssertion: The entry point exists
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <CanvasApp />
    </QueryClientProvider>
  </StrictMode>,
);
