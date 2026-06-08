import type { EngineLayoutState, PaneId, WorldRect } from "../../engine";
import type { CanvasLaunchContext } from "../route";

export type CanvasId = string;
export type ViewerId = "session-picker" | "transcript-chat" | "placeholder";
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
  | { kind: "session-timeline"; owner: "local"; sessionId: string }
  | {
      kind: "subagent-timeline";
      owner: "local";
      sessionId: string;
      subagentId: string;
      parentSessionId: string;
      parentSeq: number | null;
    }
  | { kind: "resource"; owner: "local"; sessionId: string; resourceId: string }
  | {
      kind: "provider-exchange";
      owner: "local";
      sessionId: string;
      exchangeId: string;
      initialView?: string;
    };

/**
 * The pre-slice-3 transcript ref shape. Accepted at the spawn boundary and
 * aliased onto `session-timeline` so existing session panes keep working.
 */
export type LegacyPaneContentRef = { kind: "session"; owner: "local"; sessionId: string };

/** Any ref the store will accept for spawning, including the legacy alias. */
export type SpawnablePaneRef = PaneContentRef | LegacyPaneContentRef;

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
  canRender(ref: PaneContentRef): ref is TRef;
  /** Deterministic pane id; also the dedupe key. */
  paneId(ref: TRef): PaneId;
  title(ref: TRef): string;
  /** Stable initial rect so loading content never shifts layout. */
  defaultRect(ref: TRef, index: number): WorldRect;
  render(props: ViewerProps<TRef>): React.ReactNode;
}
