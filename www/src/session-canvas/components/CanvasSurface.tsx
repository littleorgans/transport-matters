import { useCallback } from "react";
import { LayoutCanvas } from "../../engine";
import type { LaunchResolutionStatus } from "../api/launchResolution";
import { useCanvasStore } from "../model/canvasStore";
import type { CanvasLaunchContext } from "../route";
import { PICKER_PANE_ID, renderPaneContent } from "../viewers/registry";
import { CanvasCommandBar } from "./CanvasCommandBar";
import { PaneWindow } from "./PaneWindow";

export interface CanvasSurfaceProps {
  launch: CanvasLaunchContext;
  launchStatus: LaunchResolutionStatus;
  launchSessionId: string | null;
}

export function CanvasSurface({ launch, launchStatus, launchSessionId }: CanvasSurfaceProps) {
  const layout = useCanvasStore((state) => state.layout);
  const panes = useCanvasStore((state) => state.panes);
  const canvasId = useCanvasStore((state) => state.id);
  const workspaceHash = useCanvasStore((state) => state.workspaceHash);
  const focusPane = useCanvasStore((state) => state.focusPane);
  const closePane = useCanvasStore((state) => state.closePane);
  const movePane = useCanvasStore((state) => state.movePane);
  const resizePane = useCanvasStore((state) => state.resizePane);
  const setViewport = useCanvasStore((state) => state.setViewport);
  const resetViewport = useCanvasStore((state) => state.resetViewport);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
  const focusedPaneId = layout.focusedPaneId;
  const focusedTitle = focusedPaneId ? (panes[focusedPaneId]?.title ?? null) : null;

  // Stable across viewport-only renders so the memoized PaneLayer skips the pane subtree on pan/zoom.
  // Re-created only when the data it reads changes (panes, focus, actions, launch context).
  const renderPane = useCallback(
    (paneId: string) => {
      const pane = panes[paneId];
      if (!pane) return null;
      const titleId = titleIdForPane(paneId);
      const content = renderPaneContent({
        pane,
        actions: { closePane, focusPane, spawnOrFocusTranscript },
        canvas: {
          id: canvasId,
          owner: "local",
          workspaceHash,
          focusedPaneId,
          launch,
          launchStatus,
          launchSessionId,
        },
      });
      return (
        <PaneWindow
          focused={focusedPaneId === paneId}
          onClose={() => closePane(paneId)}
          pane={pane}
          titleId={titleId}
        >
          {content}
        </PaneWindow>
      );
    },
    [
      panes,
      closePane,
      focusPane,
      spawnOrFocusTranscript,
      canvasId,
      workspaceHash,
      focusedPaneId,
      launch,
      launchStatus,
      launchSessionId,
    ],
  );

  return (
    <main className="canvas-route-shell">
      <CanvasCommandBar
        focusedTitle={focusedTitle}
        launch={launch}
        onFocusPicker={() => focusPane(PICKER_PANE_ID)}
        onResetViewport={resetViewport}
      />
      <LayoutCanvas
        label={`Session canvas, ${layout.mode} mode`}
        layout={layout}
        onFocusPane={focusPane}
        onMovePane={movePane}
        onResizePane={resizePane}
        renderPane={renderPane}
        setViewport={setViewport}
        titleIdForPane={titleIdForPane}
      />
    </main>
  );
}

function titleIdForPane(paneId: string): string {
  return `canvas-pane-title-${paneId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}
