import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@tm/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ChannelBadge } from "./ChannelBadge";
import { WindowDragRegion } from "./WindowDragRegion";

export interface MountedWindowChrome {
  host: HTMLElement;
  unmount(): void;
}

export function mountWindowChrome(): MountedWindowChrome {
  const host = document.createElement("div");
  document.body.prepend(host);
  const root = createRoot(host);
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <WindowDragRegion />
        <ChannelBadge />
      </QueryClientProvider>
    </StrictMode>,
  );
  return {
    host,
    unmount() {
      root.unmount();
      host.remove();
    },
  };
}
