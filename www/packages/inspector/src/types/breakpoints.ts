export interface BreakpointStatusDetail {
  mode: "off" | "armed_once";
  paused_flows: Array<{ flow_id: string; paused_at_ms: number }>;
}
