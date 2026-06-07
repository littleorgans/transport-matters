import { useCanvasLabStore } from "../canvasLabStore";

// Stub content that shows its own live rect size — handy when eyeballing a strategy's output.
export function LabRulerPane({ paneId }: { paneId: string }) {
  const rect = useCanvasLabStore((state) => state.layout.nodes[paneId]?.rect);
  return (
    <div className="canvas-stress-card">
      <strong>{paneId}</strong>
      <div>{rect ? `${Math.round(rect.width)} × ${Math.round(rect.height)}` : "—"}</div>
    </div>
  );
}
