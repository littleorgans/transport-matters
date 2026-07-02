import { ComingSoonRoute } from "./RouteAtmosphere";

const recallRoute = {
  title: "Recall",
  label: "Session browser",
  body: "Discover what happened in prior Claude Code sessions. Search across captured exchanges, replay with or without saved overlays, and surface context that would otherwise stay buried in a week-old session log.",
  accent: "sky",
} as const;

export function RecallView() {
  return <ComingSoonRoute {...recallRoute} />;
}
