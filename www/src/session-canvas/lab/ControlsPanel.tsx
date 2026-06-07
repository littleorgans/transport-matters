import { resolveLayout } from "../../engine/layout";
import { useCanvasLabStore } from "./canvasLabStore";

// Auto-renders the active strategy's declarative controls. There is NO per-strategy UI code:
// number -> range, toggle -> checkbox, enum -> select. A new strategy's controls appear here for
// free (the §6 extensibility proof).
export function ControlsPanel() {
  const activeStrategyId = useCanvasLabStore((state) => state.activeStrategyId);
  const params = useCanvasLabStore((state) => state.params);
  const setParam = useCanvasLabStore((state) => state.setParam);
  const controls = resolveLayout(activeStrategyId).controls;

  return (
    <fieldset aria-label="Layout controls" className="canvas-lab-controls">
      {controls.map((control) => {
        const value = params[control.key];
        if (control.kind === "number") {
          return (
            <label className="canvas-lab-controls__field" key={control.key}>
              <span>{control.label}</span>
              <input
                max={control.max}
                min={control.min}
                onChange={(event) => setParam(control.key, Number(event.target.value))}
                step={control.step}
                type="range"
                value={typeof value === "number" ? value : control.min}
              />
              <output>{typeof value === "number" ? round(value) : ""}</output>
            </label>
          );
        }
        if (control.kind === "toggle") {
          return (
            <label className="canvas-lab-controls__field" key={control.key}>
              <span>{control.label}</span>
              <input
                checked={value === true}
                onChange={(event) => setParam(control.key, event.target.checked)}
                type="checkbox"
              />
            </label>
          );
        }
        return (
          <label className="canvas-lab-controls__field" key={control.key}>
            <span>{control.label}</span>
            <select
              onChange={(event) => setParam(control.key, event.target.value)}
              value={typeof value === "string" ? value : (control.options[0]?.value ?? "")}
            >
              {control.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        );
      })}
    </fieldset>
  );
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
