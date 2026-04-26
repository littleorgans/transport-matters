import type { CSSProperties } from "react";

export type AgentRailStyle = CSSProperties & {
  "--agent-rail": string;
  "--agent-rail-rgb": string;
};

const AGENT_RAILS = [
  { color: "var(--color-agent-rail-0)", rgb: "var(--agent-rail-0-rgb)" },
  { color: "var(--color-agent-rail-1)", rgb: "var(--agent-rail-1-rgb)" },
  { color: "var(--color-agent-rail-2)", rgb: "var(--agent-rail-2-rgb)" },
  { color: "var(--color-agent-rail-3)", rgb: "var(--agent-rail-3-rgb)" },
  { color: "var(--color-agent-rail-4)", rgb: "var(--agent-rail-4-rgb)" },
  { color: "var(--color-agent-rail-5)", rgb: "var(--agent-rail-5-rgb)" },
] as const;

function hashTrackId(trackId: string): number {
  let hash = 0;
  for (let index = 0; index < trackId.length; index += 1) {
    hash = (hash * 31 + trackId.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function agentRailStyle(trackId: string | null | undefined): AgentRailStyle {
  const rail = AGENT_RAILS[hashTrackId(trackId ?? "root") % AGENT_RAILS.length] ?? AGENT_RAILS[0];
  return {
    "--agent-rail": rail.color,
    "--agent-rail-rgb": rail.rgb,
  };
}
