import type { ReactNode } from "react";
import { type ProvenanceKind, ProvenanceLabel } from "./provenance";

/** Byte window a too-large resource can still preview. */
export interface PreviewRange {
  startByte: number;
  endByte: number;
}

/**
 * The eight stable states every resource pane must be able to render (frontend
 * spec, "Resource Pane States"). Slice 5 scaffolds the shells; slices 6-8 drive
 * the state from the resource content endpoint. `ready` carries no payload here
 * because real content arrives through the `children` slot.
 */
export type ResourcePaneState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "missing" }
  | { status: "too-large"; byteSize?: number; previewRange?: PreviewRange }
  | { status: "binary-unsupported"; mediaType?: string }
  | { status: "outside-workspace"; path?: string }
  | { status: "permission-denied" }
  | { status: "debug-unavailable" };

export type ResourcePaneStatus = ResourcePaneState["status"];

/** A keyboard-reachable affordance kept on the pane even when content failed. */
export interface PaneAction {
  label: string;
  onActivate?: () => void;
}

type PaneTone = "default" | "busy" | "error";

const STATE_TONE: Record<ResourcePaneStatus, PaneTone> = {
  loading: "busy",
  ready: "default",
  missing: "error",
  "too-large": "error",
  "binary-unsupported": "error",
  "outside-workspace": "error",
  "permission-denied": "error",
  "debug-unavailable": "error",
};

// Default affordance per state. Errors keep an action so the pane never collapses
// into a generic toast (frontend spec, "Resource Pane States"). Handlers stay
// undefined until slices 6-8 wire them; the affordance is present meanwhile.
const DEFAULT_ACTIONS: Record<ResourcePaneStatus, PaneAction[]> = {
  loading: [],
  ready: [],
  missing: [{ label: "Retry" }],
  "too-large": [{ label: "Load preview" }],
  "binary-unsupported": [{ label: "Open externally" }],
  "outside-workspace": [{ label: "Reveal path" }],
  "permission-denied": [{ label: "Retry" }],
  "debug-unavailable": [{ label: "Enable debug" }],
};

/**
 * The shared pane shell. Always renders the provenance label and any actions, so
 * every state (and the placeholder body) keeps its truth label and affordances.
 */
export function PaneStateFrame({
  status,
  provenance,
  tone = "default",
  header,
  actions,
  children,
}: {
  status: string;
  provenance: ProvenanceKind;
  tone?: PaneTone;
  header?: ReactNode;
  actions?: PaneAction[];
  children: ReactNode;
}) {
  return (
    <section
      aria-busy={tone === "busy" ? true : undefined}
      className="canvas-resource-pane"
      data-status={status}
      data-tone={tone}
      role={tone === "error" ? "alert" : undefined}
    >
      {header}
      <ProvenanceLabel kind={provenance} />
      <div className="canvas-resource-pane__body">{children}</div>
      <PaneActionsBar actions={actions} />
    </section>
  );
}

/** Maps one of the eight states to a stable shell. `children` fills `ready`. */
export function ResourcePaneStateView({
  state,
  provenance,
  header,
  actions,
  children,
}: {
  state: ResourcePaneState;
  provenance: ProvenanceKind;
  header?: ReactNode;
  actions?: PaneAction[];
  children?: ReactNode;
}) {
  return (
    <PaneStateFrame
      actions={actions ?? DEFAULT_ACTIONS[state.status]}
      header={header}
      provenance={provenance}
      status={state.status}
      tone={STATE_TONE[state.status]}
    >
      <StateBody state={state}>{children}</StateBody>
    </PaneStateFrame>
  );
}

function PaneActionsBar({ actions }: { actions?: PaneAction[] }) {
  if (!actions || actions.length === 0) return null;
  return (
    <div className="canvas-resource-pane__actions">
      {actions.map((action) => (
        <button
          className="canvas-button"
          key={action.label}
          onClick={action.onActivate}
          type="button"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}

function StateBody({ state, children }: { state: ResourcePaneState; children?: ReactNode }) {
  switch (state.status) {
    case "loading":
      return (
        <div aria-hidden="true" className="canvas-resource-pane__skeleton">
          <div className="canvas-picker__skeleton" />
          <div className="canvas-picker__skeleton" />
        </div>
      );
    case "ready":
      return <>{children}</>;
    case "missing":
      return (
        <StateMessage
          detail="This resource is no longer available in the run store."
          title="Resource not found"
        />
      );
    case "too-large":
      return <StateMessage detail={tooLargeDetail(state)} title="Resource too large to inline" />;
    case "binary-unsupported":
      return (
        <StateMessage
          detail={
            state.mediaType
              ? `Media type ${state.mediaType} has no inline viewer.`
              : "This binary has no inline viewer."
          }
          title="Binary resource unsupported"
        />
      );
    case "outside-workspace":
      return (
        <StateMessage
          detail={
            state.path
              ? `${state.path} resolves outside the captured workspace.`
              : "This path resolves outside the captured workspace."
          }
          title="Path is outside the workspace"
        />
      );
    case "permission-denied":
      return (
        <StateMessage
          detail="The run store denied access to this resource."
          title="Permission denied"
        />
      );
    case "debug-unavailable":
      return (
        <StateMessage
          detail="Raw provider bytes are not retained for this turn."
          title="Debug data unavailable"
        />
      );
  }
}

function tooLargeDetail(state: Extract<ResourcePaneState, { status: "too-large" }>): string {
  const size = state.byteSize ? `${state.byteSize} bytes total. ` : "";
  const range = state.previewRange
    ? `Preview bytes ${state.previewRange.startByte} to ${state.previewRange.endByte}.`
    : "No preview available.";
  return `${size}${range}`;
}

function StateMessage({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="canvas-resource-pane__message">
      <p className="canvas-resource-pane__message-title">{title}</p>
      <p className="canvas-resource-pane__message-detail">{detail}</p>
    </div>
  );
}
