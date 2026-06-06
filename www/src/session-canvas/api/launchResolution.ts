import type { CanvasLaunchContext } from "../route";
import type { SessionSummary } from "./sessionClient";

export type LaunchResolutionStatus = "pending" | "resolved" | "unavailable";

export interface LaunchResolution {
  status: LaunchResolutionStatus;
  session?: SessionSummary;
}

export function resolveLaunchSession(
  sessions: readonly SessionSummary[],
  launch: CanvasLaunchContext,
): LaunchResolution {
  if (!launch.workspaceHash || !launch.cli) return { status: "unavailable" };
  if (launch.runId) {
    const exact = sessions.find((session) => session.run_id === launch.runId);
    if (exact) return { status: "resolved", session: exact };
  }
  const active = sessions.find(
    (session) => session.status === "active" && session.workspace_hash === launch.workspaceHash,
  );
  if (active) return { status: "resolved", session: active };
  return { status: "pending" };
}
