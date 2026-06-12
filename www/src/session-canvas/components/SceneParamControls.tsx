import { sceneRegistry } from "../../ambient/sceneRegistry";
import { useThemeStore } from "../../stores/themeStore";

/**
 * Data-driven tuning sliders for the active theme's scene, one per param in
 * the scene registry (the sea scenes expose dayProgress, the 0..1 day-night
 * cycle). Scrubbing writes settings.sceneParams through the store, which the
 * ambient backdrop live-applies per frame. Renders nothing while unthemed or
 * when the scene has no params, so paramless scenes cost no chrome.
 */
export function SceneParamControls() {
  const settings = useThemeStore((state) => state.theme?.settings ?? null);
  const setSceneParam = useThemeStore((state) => state.setSceneParam);
  if (!settings) return null;
  const params = sceneRegistry.paramsFor(settings.sceneId);
  if (params.length === 0) return null;
  return (
    <>
      {params.map((param) => (
        <label className="canvas-lab-toggle canvas-scene-param" key={param.id}>
          {param.label}
          <input
            aria-label={`Scene ${param.label}`}
            max={param.max}
            min={param.min}
            onChange={(event) => setSceneParam(param.id, Number(event.target.value))}
            step={param.step}
            type="range"
            value={settings.sceneParams[param.id] ?? param.defaultValue}
          />
        </label>
      ))}
    </>
  );
}
