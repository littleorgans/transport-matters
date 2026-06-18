import type { HarnessName } from "../../types";
import { harnessLabel } from "../model/paneRecords";
import type { CanvasLaunchContext } from "../route";
import { RouteSwitcher } from "./RouteSwitcher";
import { ThemeCycleButton } from "./ThemeCycleButton";

const CAPTURED_RUN_PROVIDERS = ["claude", "codex"] as const satisfies readonly HarnessName[];

export interface CanvasCommandBarProps {
  launch: CanvasLaunchContext;
  focusedTitle: string | null;
  onFocusPicker(): void;
  onResetViewport(): void;
  onSpawnCapturedRun(provider: HarnessName): void;
}

export function CanvasCommandBar({
  launch,
  focusedTitle,
  onFocusPicker,
  onResetViewport,
  onSpawnCapturedRun,
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
        {CAPTURED_RUN_PROVIDERS.map((provider) => {
          const label = `Spawn ${harnessLabel(provider)}`;
          return (
            <button
              aria-label={label}
              className="canvas-button"
              key={provider}
              onClick={() => onSpawnCapturedRun(provider)}
              type="button"
            >
              {label}
            </button>
          );
        })}
        <ThemeCycleButton />
      </div>
      <p className="canvas-command-bar__status" aria-live="polite">
        Focus: {focusedTitle ?? "none"}
      </p>
    </div>
  );
}
