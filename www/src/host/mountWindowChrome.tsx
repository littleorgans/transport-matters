import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { queryClient } from "../lib/queryClient";
import { ChannelBadge } from "./ChannelBadge";
import { WindowDragRegion } from "./WindowDragRegion";

export function mountWindowChrome(): HTMLElement {
  const host = document.createElement("div");
  document.body.prepend(host);
  createRoot(host).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <WindowDragRegion />
        <ChannelBadge />
      </QueryClientProvider>
    </StrictMode>,
  );
  return host;
}
