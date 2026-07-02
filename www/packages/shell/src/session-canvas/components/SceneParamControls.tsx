import { useEffect, useState } from "react";
import type { AmbientSceneParamMetadata } from "../../ambient/sceneRegistry";
import { sceneRegistry } from "../../ambient/sceneRegistry";
import { useThemeStore } from "../../stores/themeStore";
import {
  clockDayToScene,
  DAY_PROGRESS_PARAM_ID,
  LIVE_DAY_INTERVAL_MS,
  localDayProgress,
  sceneDayToClock,
} from "../../theme/dayCycle";
import type { ThemeSettings } from "../../theme/types";

/**
 * Data-driven tuning sliders for the active theme's scene, one per param in
 * the scene registry (the sea scenes expose dayProgress, the 0..1 day-night
 * cycle). Scrubbing writes settings.sceneParams through the store, which the
 * ambient backdrop live-applies per frame. Renders nothing while unthemed or
 * when the scene has no params, so paramless scenes cost no chrome.
 *
 * The dayProgress param additionally carries a Live toggle (default on): in
 * live mode the slider mirrors the real local clock and dragging it drops
 * back to manual. The live value never enters the stored theme.
 */
export function SceneParamControls() {
  const settings = useThemeStore((state) => state.theme?.settings ?? null);
  if (!settings) return null;
  const params = sceneRegistry.paramsFor(settings.sceneId);
  if (params.length === 0) return null;
  return (
    <>
      {params.map((param) => (
        <SceneParamRow key={param.id} param={param} settings={settings} />
      ))}
    </>
  );
}

function SceneParamRow({
  param,
  settings,
}: {
  param: AmbientSceneParamMetadata;
  settings: ThemeSettings;
}) {
  const setSceneParam = useThemeStore((state) => state.setSceneParam);
  const liveDayCycle = useThemeStore((state) => state.liveDayCycle);
  const setLiveDayCycle = useThemeStore((state) => state.setLiveDayCycle);

  const isDayParam = param.id === DAY_PROGRESS_PARAM_ID;
  const live = isDayParam && liveDayCycle;
  const clockValue = useClockDayProgress(live);

  // The day slider speaks wall-clock time in BOTH modes; storage and the
  // renderer keep raw scene units, converted only at this boundary. One
  // display domain means the live -> manual handoff is continuous: grabbing
  // the live thumb just past midnight and nudging it stays night instead of
  // snapping to the scene's dawn-at-0.
  const stored = settings.sceneParams[param.id] ?? param.defaultValue;
  const value = isDayParam
    ? live
      ? (clockValue ?? localDayProgress(new Date()))
      : sceneDayToClock(stored)
    : stored;

  return (
    <>
      <label className="canvas-lab-toggle canvas-scene-param">
        {param.label}
        <input
          aria-label={`Scene ${param.label}`}
          max={param.max}
          min={param.min}
          onChange={(event) => {
            if (live) setLiveDayCycle(false);
            const raw = Number(event.target.value);
            setSceneParam(param.id, isDayParam ? clockDayToScene(raw) : raw);
          }}
          step={param.step}
          type="range"
          value={value}
        />
      </label>
      {isDayParam ? (
        <label className="canvas-lab-toggle">
          <input
            checked={liveDayCycle}
            onChange={(event) => setLiveDayCycle(event.target.checked)}
            type="checkbox"
          />
          Live
        </label>
      ) : null}
    </>
  );
}

/** Mirrors the local clock while active so the live slider position is honest. */
function useClockDayProgress(active: boolean): number | null {
  const [value, setValue] = useState<number | null>(null);
  useEffect(() => {
    if (!active) {
      setValue(null);
      return;
    }
    const tick = () => setValue(localDayProgress(new Date()));
    tick();
    const timer = window.setInterval(tick, LIVE_DAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return value;
}
