import { PaneSizeReadout } from "./PaneSizeReadout";

// Stub content that shows its own live rect size — handy when eyeballing a strategy's output.
export function LabRulerPane({ paneId }: { paneId: string }) {
  return (
    <div className="canvas-stress-card">
      <strong>{paneId}</strong>
      <PaneSizeReadout paneId={paneId} />
    </div>
  );
}
