// Playwright freezes the page clock to this instant so the elapsed timer,
// relative timestamps, and any `Date.now()`-derived state read the same
// on every run. Pick any stable point in time.
export const FROZEN_NOW = new Date("2026-04-14T10:00:00Z");

// Paused 3:28 ago. Matches the elapsed value in the original screenshot.
export const PAUSED_AT_MS = FROZEN_NOW.getTime() - 208_000;
