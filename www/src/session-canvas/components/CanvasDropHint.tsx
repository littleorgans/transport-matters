import { useEffect } from "react";
import type { ReactElement } from "react";
import "./pane-dock.css";

const HINT_DISMISS_MS = 4000;

export function CanvasDropHint({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}): ReactElement {
  useEffect(() => {
    const timer = setTimeout(onDismiss, HINT_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <p className="canvas-drop-hint" role="status">
      {message}
    </p>
  );
}
