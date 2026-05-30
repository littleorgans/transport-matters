import { ComingSoonRoute } from "./RouteAtmosphere";

const traceRoute = {
  title: "Trace",
  label: "Topology view",
  body: "A non-interactive diagram of every exchange in this session, the overlays that shaped each one, and the paths the provider took in response.",
  accent: "lavender",
} as const;

export function TraceView() {
  return <ComingSoonRoute {...traceRoute} />;
}
