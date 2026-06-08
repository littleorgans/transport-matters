import type { PaneContentRef, ViewerProps } from "../../model/paneRecords";
import { PaneStateFrame } from "./paneState";
import type { ProvenanceKind } from "./provenance";

/** Content kinds that resolve to the placeholder renderer until their real viewers land. */
export type PlaceholderPaneRef = Extract<
  PaneContentRef,
  { kind: "subagent-timeline" | "resource" | "provider-exchange" }
>;

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
  switch (ref.kind) {
    case "subagent-timeline":
      return {
        kindLabel: "Subagent timeline",
        rows: [
          { label: "Subagent", value: ref.subagentId },
          { label: "Session", value: ref.sessionId },
          { label: "Parent session", value: ref.parentSessionId },
          {
            label: "Parent seq",
            value: ref.parentSeq === null ? NULL_VALUE : String(ref.parentSeq),
          },
        ],
      };
    case "resource":
      return {
        kindLabel: "Resource",
        rows: [
          { label: "Resource", value: ref.resourceId },
          { label: "Session", value: ref.sessionId },
        ],
      };
    case "provider-exchange":
      return {
        kindLabel: "Provider exchange",
        rows: [
          { label: "Exchange", value: ref.exchangeId },
          { label: "Session", value: ref.sessionId },
        ],
      };
  }
}

/** Default truth label per kind; slices 6-8 refine it from the resolver response. */
export function placeholderProvenance(ref: PlaceholderPaneRef): ProvenanceKind {
  switch (ref.kind) {
    case "subagent-timeline":
      return "native-record";
    case "resource":
      return "captured";
    case "provider-exchange":
      return "structured-wire";
  }
}

/**
 * Stable placeholder shell for the three pane kinds whose real viewers arrive in
 * later slices. Renders the registry-owned title and ref-derived identity plus a
 * clear "not yet wired" body. No data fetching and no coupling to legacy route
 * state: a provider-exchange placeholder is a shell, not the exchange detail view.
 */
export function PlaceholderPane({ pane }: ViewerProps<PlaceholderPaneRef>) {
  const ref = pane.contentRef;
  const identity = placeholderIdentity(ref);
  return (
    <PaneStateFrame
      header={<PlaceholderHeader identity={identity} title={pane.title} />}
      provenance={placeholderProvenance(ref)}
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
