import type { PaneContentRef, ViewerProps } from "../../model/paneRecords";

/** Content kinds that resolve to the placeholder renderer until their real viewers land. */
export type PlaceholderPaneRef = Extract<
  PaneContentRef,
  { kind: "subagent-timeline" | "resource" | "provider-exchange" }
>;

/**
 * Slice-3 stub. The registry selects this renderer for the new pane kinds so
 * dedupe and placement work end to end. Real content arrives in later slices.
 */
export function PlaceholderPane({ pane }: ViewerProps<PlaceholderPaneRef>) {
  return (
    <div className="canvas-transcript canvas-transcript--center" role="note">
      <p>{pane.title}</p>
      <p className="canvas-picker__hint">This pane type is coming soon.</p>
    </div>
  );
}
