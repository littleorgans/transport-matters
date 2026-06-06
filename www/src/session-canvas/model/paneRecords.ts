import type { EngineLayoutState, PaneId } from "../../engine";
import type { CanvasLaunchContext } from "../route";

export type CanvasId = string;
export type ViewerId = "session-picker" | "transcript-chat";
export type PaneChromeState = "default" | "loading" | "error" | "empty";

export interface CanvasModel {
  id: CanvasId;
  owner: "local";
  workspaceHash: string | null;
  cwd: string | null;
  launch: CanvasLaunchContext;
  layout: EngineLayoutState;
  panes: Record<PaneId, PaneRecord>;
}

export interface PaneRecord {
  paneId: PaneId;
  viewerId: ViewerId;
  title: string;
  contentRef: PaneContentRef;
  chromeState: PaneChromeState;
  createdAt: string;
  lastFocusedAt: string | null;
}

export type PaneContentRef =
  | { kind: "session-picker"; owner: "local" }
  | { kind: "session"; sessionId: string; owner: "local" };

export interface SpawnSessionDescriptor {
  session_id: string;
  title: string | null;
  provider: string;
  cli: string | null;
  cwd: string;
  status: string;
  native_session_id: string | null;
  started_at: string;
}

export interface PaneActions {
  closePane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  spawnOrFocusTranscript(session: SpawnSessionDescriptor): void;
}

export interface ViewerCanvasContext {
  id: CanvasId;
  owner: "local";
  workspaceHash: string | null;
  focusedPaneId: PaneId | null;
  launch: CanvasLaunchContext;
  launchStatus: "pending" | "resolved" | "unavailable";
  launchSessionId: string | null;
}

export interface ViewerProps<TRef extends PaneContentRef = PaneContentRef> {
  pane: PaneRecord & { contentRef: TRef };
  canvas: ViewerCanvasContext;
  actions: PaneActions;
}

export interface ViewerRegistration<TRef extends PaneContentRef = PaneContentRef> {
  id: ViewerId;
  title(ref: TRef): string;
  canRender(ref: PaneContentRef): ref is TRef;
  render(props: ViewerProps<TRef>): React.ReactNode;
}
