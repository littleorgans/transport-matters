import { isDesktopHost } from "@tm/core";

export interface WindowDragRegionProps {
  // Injectable for tests; defaults to detecting the Electron shell at render.
  desktop?: boolean;
}

// Recreates the native macOS title bar's drag behavior after the window is launched
// with titleBarStyle:"hidden". An empty, full-width strip pinned to the top edge with
// `-webkit-app-region: drag`, so pressing and dragging there moves the window exactly
// as the hidden title bar did. Rendered ONLY inside the Electron shell: a drag region
// silently swallows mouse events, so in a plain browser it would eat clicks in the top
// strip. The native traffic lights float above it and remain interactive.
export function WindowDragRegion({ desktop = isDesktopHost() }: WindowDragRegionProps = {}) {
  if (!desktop) return null;
  return <div aria-hidden="true" className="window-drag-region" />;
}
