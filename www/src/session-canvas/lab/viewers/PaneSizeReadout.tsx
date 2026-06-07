import { useCanvasLabStore } from "../canvasLabStore";

// Live world size of a pane, shown in the body so a strategy's output is easy to eyeball. Shared by
// both lab viewers so the readout never drifts between them.
export function PaneSizeReadout({ paneId }: { paneId: string }) {
  const rect = useCanvasLabStore((state) => state.layout.nodes[paneId]?.rect);
  return (
    <div className="canvas-stress-card__dims">
      {rect ? `${Math.round(rect.width)} × ${Math.round(rect.height)}` : "—"}
    </div>
  );
}
