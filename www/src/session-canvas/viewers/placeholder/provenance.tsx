// Provenance scaffold for resource panes. A pane must label which truth the user
// is seeing so the UI never claims historical file truth when only current disk
// content is available (frontend spec, "Labels And Provenance"). The kind is the
// backend-canonical ResourceContentProvenance so a fetched response maps 1:1.

import type { ResourceContentProvenance } from "../../api/resourceContent";

/** The six truths a resource pane can be showing. Owned by the backend contract. */
export type ProvenanceKind = ResourceContentProvenance;

/** Human-readable label per provenance kind. Text, never color alone (a11y). */
export const PROVENANCE_LABEL: Record<ProvenanceKind, string> = {
  current: "Current workspace content",
  captured: "Captured content",
  "inline-artifact": "Inline artifact content",
  "structured-wire": "Structured wire evidence",
  "raw-provider-debug": "Raw provider bytes (debug)",
  "native-record": "Native transcript record",
};

/** A small, always-visible chip that names the pane's truth source. */
export function ProvenanceLabel({ kind }: { kind: ProvenanceKind }) {
  return (
    <p className="canvas-resource-pane__provenance" data-provenance={kind}>
      {PROVENANCE_LABEL[kind]}
    </p>
  );
}
