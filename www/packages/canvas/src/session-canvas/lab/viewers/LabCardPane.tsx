import { PaneSizeReadout } from "./PaneSizeReadout";

// Stub content. The lab proves the LAYOUT registry, not a content registry — content is deliberately
// trivial. It reports its own live size so every pane (card or ruler) shows its planned dimensions.
export function LabCardPane({ paneId }: { paneId: string }) {
  return (
    <div className="canvas-stress-card">
      <strong>Pane {paneId}</strong>
      <PaneSizeReadout paneId={paneId} />
    </div>
  );
}
