import { LayoutCanvas } from "../../engine";
import type { LaunchResolutionStatus } from "../api/launchResolution";
import { useCanvasStore } from "../model/canvasStore";
import { PICKER_PANE_ID } from "../model/spawn";
import type { CanvasLaunchContext } from "../route";
import { resolveViewer } from "../viewers/registry";
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
  const focusedTitle = layout.focusedPaneId ? (panes[layout.focusedPaneId]?.title ?? null) : null;

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
        renderPane={(paneId) => {
          const pane = panes[paneId];
          if (!pane) return null;
          const viewer = resolveViewer(pane.contentRef);
          const titleId = titleIdForPane(paneId);
          const content = viewer.render({
            pane,
            actions: { closePane, focusPane, spawnOrFocusTranscript },
            canvas: {
              id: canvasId,
              owner: "local",
              workspaceHash,
              focusedPaneId: layout.focusedPaneId,
              launch,
              launchStatus,
              launchSessionId,
            },
          });
          return (
            <PaneWindow
              focused={layout.focusedPaneId === paneId}
              onClose={() => closePane(paneId)}
              pane={pane}
              titleId={titleId}
            >
              {content}
            </PaneWindow>
          );
        }}
        setViewport={setViewport}
        titleIdForPane={titleIdForPane}
      />
    </main>
  );
}

function titleIdForPane(paneId: string): string {
  return `canvas-pane-title-${paneId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}
