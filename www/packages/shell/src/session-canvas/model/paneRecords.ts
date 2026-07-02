import type { SpaceId, WorktreeId } from "@tm/core";
import { isRecord } from "@tm/core";
import type { HarnessName } from "@tm/core/types/capabilities";
import type { EngineLayoutState, PaneId } from "../../engine";
import type { CanvasLaunchContext } from "../route";

/** Display label for a managed harness / captured-run provider (window title, banners). */
const HARNESS_LABELS: Record<HarnessName, string> = { claude: "Claude", codex: "Codex" };

/**
 * The managed harnesses spawnable as a captured run (the "Native" agents). The
 * backend validates the same allowlist (api: _CAPTURED_RUN_HARNESS_ALLOWLIST),
 * so a runtime template recommending any other harness is not spawnable here.
 */
export const CAPTURED_RUN_PROVIDERS = ["claude", "codex"] as const satisfies readonly HarnessName[];

export function harnessLabel(provider: HarnessName): string {
  return HARNESS_LABELS[provider];
}

export function locatorTail(locator: string): string {
  return locator.split("/").filter(Boolean).at(-1) ?? locator;
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function hasLocalOwner(ref: Record<string, unknown>): boolean {
  return ref.owner === "local";
}

function isHarnessName(value: unknown): value is HarnessName {
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
  canvasId: CanvasId;
  owner: "local";
  spaceId: SpaceId | null;
  workspaceHash: string | null;
  /**
   * Promoted into the model (R3): the fallback worktree root for spawnable panes
   * (terminal / captured-run) that carry no explicit worktree of their own.
   */
  defaultWorktreeId: WorktreeId | null;
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
  | { kind: "resource"; owner: "local"; source: "url"; url: string; worktreeId?: string }
  | {
      kind: "provider-exchange";
      owner: "local";
      sessionId: string;
      runId: string;
      exchangeId: string;
      initialView?: string;
    }
  | { kind: "terminal"; owner: "local"; label?: string; worktreeId: string }
  | {
      kind: "captured-run";
      owner: "local";
      provider: HarnessName;
      runKey: string;
      label?: string;
      // Named runtime template this run launched under. Absent → NATIVE launch.
      // Persisted on the ref so a detach/restore re-attaches under the same template.
      runtimeTemplate?: string;
      // Worktree root this run is captured under (R3). Required: a captured run
      // must resolve a cwd, so it can never be worktree-less.
      worktreeId: string;
      // Durable pane→session-lineage anchor for native resume (--resume / resume)
      // and internal continuation (parent_session_id). Persisted now so canvases
      // carry it; populated on session-bind in Slice 7. Legacy panes: undefined.
      sessionId?: string;
    };

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
          (value.source === "url" &&
            typeof value.url === "string" &&
            isOptionalString(value.worktreeId))
        );
      }
      return typeof value.sessionId === "string" && typeof value.resourceId === "string";
    case "provider-exchange":
      return (
        typeof value.sessionId === "string" &&
        typeof value.runId === "string" &&
        typeof value.exchangeId === "string" &&
        isOptionalString(value.initialView)
      );
    case "terminal":
      return isOptionalString(value.label) && typeof value.worktreeId === "string";
    case "captured-run":
      return (
        isHarnessName(value.provider) &&
        typeof value.runKey === "string" &&
        isOptionalString(value.label) &&
        isOptionalString(value.runtimeTemplate) &&
        typeof value.worktreeId === "string" &&
        isOptionalString(value.sessionId)
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
  sessionId: string;
  title: string | null;
  provider: string;
  harness: string;
  status: string;
  lastActivityAt: string;
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
