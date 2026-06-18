import { lazy, type ReactNode, Suspense } from "react";
import type { PaneId } from "../../engine";
import {
  type CanvasPaneRef,
  harnessLabel,
  locatorTail,
  type PaneContentRef,
  type PaneRecord,
  type PickerPaneRef,
  type ViewerId,
  type ViewerProps,
  type ViewerRegistration,
} from "../model/paneRecords";
import { PlaceholderPane, type PlaceholderPaneRef } from "./placeholder/PlaceholderPane";
import { ProviderExchangeResourceViewer } from "./resource/ProviderExchangeResourceViewer";
import { ResourcePane } from "./resource/ResourcePane";
import { SessionPickerPane } from "./session-picker/SessionPickerPane";
import { TranscriptChatPane } from "./transcript-chat/TranscriptChatPane";

// xterm is heavy (~50KB gzip) and only needed once a terminal pane is opened, so split it into its
// own chunk instead of weighing down every canvas load. Both terminal-backed panes share the xterm
// + session core, so the bundler folds it into one shared chunk these two lazy entries pull in.
const TerminalPane = lazy(() =>
  import("./terminal/TerminalPane").then((module) => ({ default: module.TerminalPane })),
);
const CapturedRunPane = lazy(() =>
  import("./terminal/CapturedRunPane").then((module) => ({
    default: module.CapturedRunPane,
  })),
);

export const PICKER_PANE_ID = "session-picker";
const TRANSCRIPT_PANE_PREFIX = "transcript:";
const SUBAGENT_PANE_PREFIX = "subagent:";
const RESOURCE_PANE_PREFIX = "resource:";
const EXCHANGE_PANE_PREFIX = "exchange:";

/**
 * Narrows a registration to its ref kind so paneId/title/render can read ref
 * fields without casts, then erases the generic for the heterogeneous registry.
 * Safe because `resolveViewer` only calls a registration after its own
 * `canRender` guard has matched.
 */
function defineViewer<TRef extends CanvasPaneRef>(
  reg: ViewerRegistration<TRef>,
): ViewerRegistration {
  return reg as ViewerRegistration;
}

type ResourceRef = Extract<PaneContentRef, { kind: "resource" }>;
type ExchangeRef = Extract<PaneContentRef, { kind: "provider-exchange" }>;
type TerminalRef = Extract<PaneContentRef, { kind: "terminal" }>;
type CapturedRunRef = Extract<PaneContentRef, { kind: "captured-run" }>;

const registry: ViewerRegistration[] = [
  defineViewer<PickerPaneRef>({
    id: "session-picker",
    canRender: (ref): ref is PickerPaneRef => ref.kind === "session-picker",
    paneId: () => PICKER_PANE_ID,
    title: () => "Session picker",
    render: (props) => <SessionPickerPane {...props} />,
  }),
  defineViewer<Extract<PaneContentRef, { kind: "session-timeline" }>>({
    id: "transcript-chat",
    canRender: (ref): ref is Extract<PaneContentRef, { kind: "session-timeline" }> =>
      ref.kind === "session-timeline",
    paneId: (ref) => `${TRANSCRIPT_PANE_PREFIX}${ref.sessionId}`,
    title: (ref) => ref.title ?? `Transcript ${ref.sessionId.slice(0, 8)}`,
    render: (props) => <TranscriptChatPane {...props} />,
  }),
  defineViewer<ResourceRef>({
    id: "resource",
    canRender: (ref): ref is ResourceRef => ref.kind === "resource",
    bodyDrag: true,
    paneId: (ref) =>
      "source" in ref
        ? `${RESOURCE_PANE_PREFIX}${ref.source}:${ref.source === "path" ? ref.path : ref.url}`
        : `${RESOURCE_PANE_PREFIX}${ref.sessionId}:${ref.resourceId}`,
    title: (ref) => resourceRefTitle(ref),
    render: (props) => <ResourcePane {...props} />,
  }),
  defineViewer<ExchangeRef>({
    id: "provider-exchange",
    canRender: (ref): ref is ExchangeRef => ref.kind === "provider-exchange",
    paneId: (ref) => `${EXCHANGE_PANE_PREFIX}${ref.runId}:${ref.exchangeId}`,
    title: (ref) => `Exchange ${ref.exchangeId.slice(0, 8)}`,
    render: (props) => (
      <ProviderExchangeResourceViewer
        runId={props.pane.contentRef.runId}
        exchangeId={props.pane.contentRef.exchangeId}
        initialView={props.pane.contentRef.initialView}
      />
    ),
  }),
  defineViewer<TerminalRef>({
    id: "terminal",
    canRender: (ref): ref is TerminalRef => ref.kind === "terminal",
    paneId: () => "terminal",
    title: (ref) => ref.label ?? "Terminal",
    // The terminal is self-contained (its own xterm + PTY socket); it ignores viewer props. It is
    // lazy, so a Suspense boundary covers the one-time chunk fetch.
    render: (props) => (
      <Suspense
        fallback={<div aria-busy="true" className="canvas-transcript canvas-transcript--center" />}
      >
        <TerminalPane pane={props.pane} />
      </Suspense>
    ),
  }),
  defineViewer<CapturedRunRef>({
    id: "captured-run",
    canRender: (ref): ref is CapturedRunRef => ref.kind === "captured-run",
    // Each captured pane owns its own run, so the pane id IS the per-pane run key
    // (provider:uuid). Two same-provider captured runs carry distinct keys => distinct
    // pane ids; they never dedupe onto one shared terminal.
    paneId: (ref) => ref.runKey,
    title: (ref) => ref.label ?? harnessLabel(ref.provider),
    // Self-contained like the bare terminal (its own xterm + captured PTY socket). The pane id is
    // the per-pane run key, so each captured pane owns its own run. Lazy, so a Suspense boundary
    // covers the one-time shared-chunk fetch.
    render: (props) => (
      <Suspense
        fallback={<div aria-busy="true" className="canvas-transcript canvas-transcript--center" />}
      >
        <CapturedRunPane
          runKey={props.pane.contentRef.runKey}
          provider={props.pane.contentRef.provider}
          runtimeTemplate={props.pane.contentRef.runtimeTemplate}
        />
      </Suspense>
    ),
  }),
  defineViewer<PlaceholderPaneRef>({
    id: "placeholder",
    canRender: (ref): ref is PlaceholderPaneRef => ref.kind === "subagent-timeline",
    paneId: (ref) => `${SUBAGENT_PANE_PREFIX}${ref.sessionId}:${ref.subagentId}`,
    // The real backend child-session title travels on the ref (SubagentRef.title).
    title: (ref) => ref.title,
    render: (props) => <PlaceholderPane {...props} />,
  }),
];

/** Locator refs title by their file name; db refs keep the short-id title. */
function resourceRefTitle(ref: ResourceRef): string {
  if (!("source" in ref)) return `Resource ${ref.resourceId.slice(0, 8)}`;
  const locator = ref.source === "path" ? ref.path : ref.url;
  return locatorTail(locator);
}

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

export function bodyDragForRef(ref: CanvasPaneRef): boolean {
  return resolveViewer(ref).bodyDrag === true;
}

export function titleForRef(ref: CanvasPaneRef): string {
  return resolveViewer(ref).title(ref);
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
