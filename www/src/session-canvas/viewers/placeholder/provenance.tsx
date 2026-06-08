// Provenance scaffold for resource panes. A pane must label which truth the user
// is seeing so the UI never claims historical file truth when only current disk
// content is available (frontend spec, "Labels And Provenance"). Slice 5 wires the
// label structure; later slices set the kind from real resolver responses.

/** The six truths a resource pane can be showing. */
export type ProvenanceKind =
  | "current"
  | "captured"
  | "inline-artifact"
  | "structured-wire"
  | "raw-bytes"
  | "native-record";

/** Human-readable label per provenance kind. Text, never color alone (a11y). */
export const PROVENANCE_LABEL: Record<ProvenanceKind, string> = {
  current: "Current workspace content",
  captured: "Captured content",
  "inline-artifact": "Inline artifact content",
  "structured-wire": "Structured wire evidence",
  "raw-bytes": "Raw provider bytes (debug)",
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
