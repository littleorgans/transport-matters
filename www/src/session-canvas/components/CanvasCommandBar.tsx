import type { CanvasLaunchContext } from "../route";
import { RouteSwitcher } from "./RouteSwitcher";
import { ThemeCycleButton } from "./ThemeCycleButton";

export interface CanvasCommandBarProps {
  launch: CanvasLaunchContext;
  focusedTitle: string | null;
  onFocusPicker(): void;
  onResetViewport(): void;
}

export function CanvasCommandBar({
  launch,
  focusedTitle,
  onFocusPicker,
  onResetViewport,
}: CanvasCommandBarProps) {
  const workspaceLabel = launch.workspaceHash ?? "all local workspaces";
  return (
    <div aria-label="Canvas commands" className="canvas-command-bar" role="toolbar">
      <div className="canvas-command-bar__identity">
        <span>Session canvas</span>
        <span>{workspaceLabel}</span>
      </div>
      <div className="canvas-command-bar__buttons">
        <RouteSwitcher />
        <button className="canvas-button" onClick={onFocusPicker} type="button">
          Focus picker
        </button>
        <button className="canvas-button" onClick={onResetViewport} type="button">
          Reset view
        </button>
        <ThemeCycleButton />
      </div>
      <p className="canvas-command-bar__status" aria-live="polite">
        Focus: {focusedTitle ?? "none"}
      </p>
    </div>
  );
}
