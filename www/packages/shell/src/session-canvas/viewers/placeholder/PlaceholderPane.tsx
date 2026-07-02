import type { PaneContentRef, ViewerProps } from "../../model/paneRecords";
import { PaneStateFrame } from "./paneState";
import type { ProvenanceKind } from "./provenance";

/** The remaining pane kind whose real viewer has not landed yet. */
export type PlaceholderPaneRef = Extract<PaneContentRef, { kind: "subagent-timeline" }>;

interface IdentityRow {
  label: string;
  value: string;
}

interface PlaceholderIdentity {
  kindLabel: string;
  rows: IdentityRow[];
}

const NULL_VALUE = "n/a";

/** Ref-derived identity rows. Subagent reads the post-slice-4 SubagentRef shape. */
export function placeholderIdentity(ref: PlaceholderPaneRef): PlaceholderIdentity {
  return {
    kindLabel: "Subagent timeline",
    rows: [
      { label: "Subagent", value: ref.subagentId },
      { label: "Session", value: ref.sessionId },
      { label: "Parent session", value: ref.parentSessionId },
      { label: "Parent seq", value: ref.parentSeq === null ? NULL_VALUE : String(ref.parentSeq) },
    ],
  };
}

/** Truth label for the subagent placeholder; its real viewer arrives in a later slice. */
export function placeholderProvenance(): ProvenanceKind {
  return "native-record";
}

/**
 * Stable placeholder shell for the subagent pane kind, whose real viewer arrives
 * in a later slice. Renders the registry-owned title and ref-derived identity
 * plus a clear "not yet wired" body. No data fetching, no legacy route state.
 */
export function PlaceholderPane({ pane }: ViewerProps<PlaceholderPaneRef>) {
  const ref = pane.contentRef;
  const identity = placeholderIdentity(ref);
  return (
    <PaneStateFrame
      header={<PlaceholderHeader identity={identity} title={pane.title} />}
      provenance={placeholderProvenance()}
      status="placeholder"
    >
      <p className="canvas-resource-pane__note">
        This {identity.kindLabel.toLowerCase()} viewer is not yet wired. Content arrives in a later
        slice.
      </p>
    </PaneStateFrame>
  );
}

function PlaceholderHeader({ identity, title }: { identity: PlaceholderIdentity; title: string }) {
  return (
    <div className="canvas-resource-pane__header">
      <p className="canvas-resource-pane__kind">{identity.kindLabel}</p>
      <h3 className="canvas-resource-pane__title">{title}</h3>
      <dl className="canvas-resource-pane__identity">
        {identity.rows.map((row) => (
          <div className="canvas-resource-pane__id-row" key={row.label}>
            <dt className="canvas-resource-pane__id-label">{row.label}</dt>
            <dd className="canvas-resource-pane__id-value">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
