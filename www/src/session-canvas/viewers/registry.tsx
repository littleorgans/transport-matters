import type { ReactNode } from "react";
import type { PaneId, WorldRect } from "../../engine";
import type {
  CanvasPaneRef,
  PaneContentRef,
  PaneRecord,
  PickerPaneRef,
  ViewerId,
  ViewerProps,
  ViewerRegistration,
} from "../model/paneRecords";
import { PlaceholderPane, type PlaceholderPaneRef } from "./placeholder/PlaceholderPane";
import { ProviderExchangeResourceViewer } from "./resource/ProviderExchangeResourceViewer";
import { ResourcePane } from "./resource/ResourcePane";
import { SessionPickerPane } from "./session-picker/SessionPickerPane";
import { TranscriptChatPane } from "./transcript-chat/TranscriptChatPane";

export const PICKER_PANE_ID = "session-picker";
const TRANSCRIPT_PANE_PREFIX = "transcript:";
const SUBAGENT_PANE_PREFIX = "subagent:";
const RESOURCE_PANE_PREFIX = "resource:";
const EXCHANGE_PANE_PREFIX = "exchange:";

const PICKER_RECT: WorldRect = Object.freeze({ x: 48, y: 48, width: 440, height: 640 });
const TRANSCRIPT_RECT: WorldRect = Object.freeze({ x: 512, y: 48, width: 720, height: 640 });
const PLACEHOLDER_RECT: WorldRect = Object.freeze({ x: 560, y: 88, width: 560, height: 560 });
const CASCADE_OFFSET = 28;

/**
 * Narrows a registration to its ref kind so paneId/title/defaultRect/render can
 * read ref fields without casts, then erases the generic for the heterogeneous
 * registry. Safe because `resolveViewer` only calls a registration after its own
 * `canRender` guard has matched.
 */
function defineViewer<TRef extends CanvasPaneRef>(
  reg: ViewerRegistration<TRef>,
): ViewerRegistration {
  return reg as ViewerRegistration;
}

function cascadeRect(base: WorldRect, step: number): WorldRect {
  if (step <= 0) return { ...base };
  return { ...base, x: base.x + step * CASCADE_OFFSET, y: base.y + step * CASCADE_OFFSET };
}

// The picker is always present, so transcript and content panes cascade from the
// second pane onward to preserve the established placement.
function contentStep(paneCount: number): number {
  return Math.max(0, paneCount - 1);
}

type ResourceRef = Extract<PaneContentRef, { kind: "resource" }>;
type ExchangeRef = Extract<PaneContentRef, { kind: "provider-exchange" }>;

const registry: ViewerRegistration[] = [
  defineViewer<PickerPaneRef>({
    id: "session-picker",
    canRender: (ref): ref is PickerPaneRef => ref.kind === "session-picker",
    paneId: () => PICKER_PANE_ID,
    title: () => "Session picker",
    defaultRect: () => ({ ...PICKER_RECT }),
    render: (props) => <SessionPickerPane {...props} />,
  }),
  defineViewer<Extract<PaneContentRef, { kind: "session-timeline" }>>({
    id: "transcript-chat",
    canRender: (ref): ref is Extract<PaneContentRef, { kind: "session-timeline" }> =>
      ref.kind === "session-timeline",
    paneId: (ref) => `${TRANSCRIPT_PANE_PREFIX}${ref.sessionId}`,
    title: (ref) => `Transcript ${ref.sessionId.slice(0, 8)}`,
    defaultRect: (_ref, index) => cascadeRect(TRANSCRIPT_RECT, contentStep(index)),
    render: (props) => <TranscriptChatPane {...props} />,
  }),
  defineViewer<ResourceRef>({
    id: "resource",
    canRender: (ref): ref is ResourceRef => ref.kind === "resource",
    paneId: (ref) => `${RESOURCE_PANE_PREFIX}${ref.sessionId}:${ref.resourceId}`,
    title: (ref) => `Resource ${ref.resourceId.slice(0, 8)}`,
    defaultRect: (_ref, index) => cascadeRect(PLACEHOLDER_RECT, contentStep(index)),
    render: (props) => <ResourcePane {...props} />,
  }),
  defineViewer<ExchangeRef>({
    id: "provider-exchange",
    canRender: (ref): ref is ExchangeRef => ref.kind === "provider-exchange",
    paneId: (ref) => `${EXCHANGE_PANE_PREFIX}${ref.sessionId}:${ref.exchangeId}`,
    title: (ref) => `Exchange ${ref.exchangeId.slice(0, 8)}`,
    defaultRect: (_ref, index) => cascadeRect(PLACEHOLDER_RECT, contentStep(index)),
    render: (props) => (
      <ProviderExchangeResourceViewer
        exchangeId={props.pane.contentRef.exchangeId}
        initialView={props.pane.contentRef.initialView}
      />
    ),
  }),
  defineViewer<PlaceholderPaneRef>({
    id: "placeholder",
    canRender: (ref): ref is PlaceholderPaneRef => ref.kind === "subagent-timeline",
    paneId: (ref) => `${SUBAGENT_PANE_PREFIX}${ref.sessionId}:${ref.subagentId}`,
    // The real backend child-session title travels on the ref (SubagentRef.title).
    title: (ref) => ref.title,
    defaultRect: (_ref, index) => cascadeRect(PLACEHOLDER_RECT, contentStep(index)),
    render: (props) => <PlaceholderPane {...props} />,
  }),
];

export function registerViewer(viewer: ViewerRegistration): void {
  const existingIndex = registry.findIndex((entry) => entry.id === viewer.id);
  if (existingIndex >= 0) registry[existingIndex] = viewer;
  else registry.push(viewer);
}

export function resolveViewer(ref: CanvasPaneRef): ViewerRegistration {
  const viewer = registry.find((entry) => entry.canRender(ref));
  if (!viewer) throw new Error(`No viewer registered for ${ref.kind}.`);
  return viewer;
}

/** Registry-owned dedupe key for a ref. */
export function paneIdForRef(ref: CanvasPaneRef): PaneId {
  return resolveViewer(ref).paneId(ref);
}

export function titleForRef(ref: CanvasPaneRef): string {
  return resolveViewer(ref).title(ref);
}

export function rectForRef(ref: CanvasPaneRef, paneCount: number): WorldRect {
  return resolveViewer(ref).defaultRect(ref, paneCount);
}

export function viewerIdForRef(ref: CanvasPaneRef): ViewerId {
  return resolveViewer(ref).id;
}

/** Renderer selection plus the shared loading/error shell. */
export function renderPaneContent(props: ViewerProps): ReactNode {
  const viewer = resolveViewer(props.pane.contentRef);
  return <PaneShell pane={props.pane}>{viewer.render(props)}</PaneShell>;
}

function PaneShell({ pane, children }: { pane: PaneRecord; children: ReactNode }) {
  switch (pane.chromeState) {
    case "loading":
      return (
        <div className="canvas-transcript canvas-transcript--center" aria-busy="true">
          <div className="canvas-picker__skeleton" />
          <div className="canvas-picker__skeleton" />
        </div>
      );
    case "error":
      return (
        <div className="canvas-transcript canvas-transcript--center" role="alert">
          <p>{pane.title} failed to load.</p>
        </div>
      );
    case "empty":
      return (
        <div className="canvas-transcript canvas-transcript--center">
          <p>Nothing to show.</p>
        </div>
      );
    default:
      return <>{children}</>;
  }
}
