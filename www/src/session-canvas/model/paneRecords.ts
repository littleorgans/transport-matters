import type { EngineLayoutState, PaneId } from "../../engine";
import type { CliName } from "../../types";
import type { CanvasLaunchContext } from "../route";

/** Display label for a managed CLI / captured-run provider (window title, banners). */
const CLI_LABELS: Record<CliName, string> = { claude: "Claude", codex: "Codex" };

export function cliLabel(provider: CliName): string {
  return CLI_LABELS[provider];
}

export function locatorTail(locator: string): string {
  return locator.split("/").filter(Boolean).at(-1) ?? locator;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function hasLocalOwner(ref: Record<string, unknown>): boolean {
  return ref.owner === "local";
}

function isCliName(value: unknown): value is CliName {
  return value === "claude" || value === "codex";
}

export type CanvasId = string;
export type ViewerId =
  | "session-picker"
  | "transcript-chat"
  | "placeholder"
  | "resource"
  | "provider-exchange"
  | "terminal"
  | "captured-run";
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
  contentRef: CanvasPaneRef;
  chromeState: PaneChromeState;
  createdAt: string;
  lastFocusedAt: string | null;
}

export type PaneContentRef =
  | { kind: "session-timeline"; owner: "local"; sessionId: string; title?: string }
  | {
      kind: "subagent-timeline";
      owner: "local";
      sessionId: string;
      subagentId: string;
      parentSessionId: string;
      parentSeq: number | null;
      title: string;
    }
  | { kind: "resource"; owner: "local"; sessionId: string; resourceId: string }
  | { kind: "resource"; owner: "local"; source: "path"; path: string }
  | { kind: "resource"; owner: "local"; source: "url"; url: string }
  | {
      kind: "provider-exchange";
      owner: "local";
      sessionId: string;
      exchangeId: string;
      initialView?: string;
    }
  | { kind: "terminal"; owner: "local"; label?: string }
  | { kind: "captured-run"; owner: "local"; provider: CliName; runKey: string; label?: string };

/**
 * A pane removed from the canvas but retained locally so the dock can restore it (Option A: local
 * minimized state only, no `/v1/runs`). `ref` is the viewer ref to re-seed on restore; `null` for
 * demo card/ruler stubs that carry no ref (the node is re-created from the pane id alone). Production
 * may also park the full PaneRecord so restore preserves user-facing pane metadata exactly.
 */
export interface DockedPane {
  paneId: PaneId;
  ref: CanvasPaneRef | null;
  /** Production /canvas parks the full record so restore keeps its exact title and timestamps. */
  record?: PaneRecord;
  /** True for protected chrome panes that may restore but not be killed from the dock. */
  closeDisabled?: boolean;
}

/** The built-in session picker is canvas chrome, not transcript content. */
export type PickerPaneRef = { kind: "session-picker"; owner: "local" };

/** Every pane the canvas manages: the picker plus opened transcript content. */
export type CanvasPaneRef = PickerPaneRef | PaneContentRef;

export function isPaneContentRef(value: unknown): value is PaneContentRef {
  if (!isRecord(value) || !hasLocalOwner(value)) return false;
  switch (value.kind) {
    case "session-timeline":
      return typeof value.sessionId === "string" && isOptionalString(value.title);
    case "subagent-timeline":
      return (
        typeof value.sessionId === "string" &&
        typeof value.subagentId === "string" &&
        typeof value.parentSessionId === "string" &&
        (typeof value.parentSeq === "number" || value.parentSeq === null) &&
        typeof value.title === "string"
      );
    case "resource":
      if ("source" in value) {
        return (
          (value.source === "path" && typeof value.path === "string") ||
          (value.source === "url" && typeof value.url === "string")
        );
      }
      return typeof value.sessionId === "string" && typeof value.resourceId === "string";
    case "provider-exchange":
      return (
        typeof value.sessionId === "string" &&
        typeof value.exchangeId === "string" &&
        isOptionalString(value.initialView)
      );
    case "terminal":
      return isOptionalString(value.label);
    case "captured-run":
      return (
        isCliName(value.provider) &&
        typeof value.runKey === "string" &&
        isOptionalString(value.label)
      );
    default:
      return false;
  }
}

export function isCanvasPaneRef(value: unknown): value is CanvasPaneRef {
  return (
    (isRecord(value) && value.kind === "session-picker" && hasLocalOwner(value)) ||
    isPaneContentRef(value)
  );
}

/**
 * The pre-slice-3 transcript ref shape. Accepted at the spawn boundary and
 * aliased onto `session-timeline` so existing session panes keep working.
 */
export type LegacyPaneContentRef = { kind: "session"; owner: "local"; sessionId: string };

/** Any ref the store will accept for spawning, including the legacy alias. */
export type SpawnablePaneRef = CanvasPaneRef | LegacyPaneContentRef;

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

export interface ViewerProps<TRef extends CanvasPaneRef = CanvasPaneRef> {
  pane: PaneRecord & { contentRef: TRef };
  canvas: ViewerCanvasContext;
  actions: PaneActions;
}

export interface ViewerRegistration<TRef extends CanvasPaneRef = CanvasPaneRef> {
  id: ViewerId;
  canRender(ref: CanvasPaneRef): ref is TRef;
  /** Deterministic pane id; also the dedupe key. */
  paneId(ref: TRef): PaneId;
  title(ref: TRef): string;
  /** Body pointer-drags lift the pane (resource panes: grab the image, grab the pane). */
  bodyDrag?: boolean;
  render(props: ViewerProps<TRef>): React.ReactNode;
}
