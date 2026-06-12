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

/** 0..1 position of `date` within its local day, the dayProgress domain. */
export function localDayProgress(date: Date): number {
  const seconds = date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
  return seconds / SECONDS_PER_DAY;
}
