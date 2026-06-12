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
 * Convert clock time into the scene's domain so noon renders the high sun and
 * just-past-midnight renders night, not dawn. Host-side compensation observed
 * from rendered output; drops to identity if the lab re-phases the scene.
 */
const SCENE_HIGH_SUN = 0.25;
const CLOCK_NOON = 0.5;

export function sceneDayProgress(date: Date): number {
  return (localDayProgress(date) - (CLOCK_NOON - SCENE_HIGH_SUN) + 1) % 1;
}
