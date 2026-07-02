/**
 * The live day-night clock. dayProgress is the sea scenes' 0..1 day-cycle
 * param; in live mode it tracks the actual local clock, so the sun sits where
 * the real one does and moves imperceptibly minute to minute (Stuart chose
 * accuracy over visible motion; the waves still animate fast via uTime).
 *
 * The live value is runtime-only: it is pushed straight into the renderer and
 * never written to settings.sceneParams, so a saved or exported theme carries
 * the manual baseline, not a time of day.
 */
export const DAY_PROGRESS_PARAM_ID = "dayProgress";

/** The clock rate is one sun-degree every four minutes; 30s ticks are plenty. */
export const LIVE_DAY_INTERVAL_MS = 30_000;

const SECONDS_PER_DAY = 86_400;

/** 0..1 position of `date` within its local day: midnight 0, noon 0.5. */
export function localDayProgress(date: Date): number {
  const seconds = date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
  return seconds / SECONDS_PER_DAY;
}

/**
 * The sea scenes' sun curve is phased with dawn at 0 and the high sun at 0.25
 * (the scene default renders full day), while wall clock puts midnight at 0.
 * Convert between the two domains so noon renders the high sun and
 * just-past-midnight renders night, not dawn. The day slider always displays
 * wall-clock time; storage and the renderer always carry raw scene units
 * (the lab contract), so these two converters are the single seam between
 * them. Confirmed against the shader by the lab (2026-06-13); both collapse
 * to identity if the scene is ever re-phased.
 */
const SCENE_HIGH_SUN = 0.25;
const CLOCK_NOON = 0.5;
const DAWN_SHIFT = CLOCK_NOON - SCENE_HIGH_SUN;

/* Round to well below the sliders' 0.001 step so converted values neither
   wobble the thumb nor leak float noise into stored/exported sceneParams. */
const round6 = (value: number): number => Math.round(value * 1e6) / 1e6;

export const clockDayToScene = (clock: number): number => round6((clock - DAWN_SHIFT + 1) % 1);
export const sceneDayToClock = (scene: number): number => round6((scene + DAWN_SHIFT) % 1);

export function sceneDayProgress(date: Date): number {
  return clockDayToScene(localDayProgress(date));
}
