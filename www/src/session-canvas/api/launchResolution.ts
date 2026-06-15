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
  const workspaceHash = launch.workspaceHash;
  const cli = launch.cli;
  const active = sessions.find(
    (session) =>
      session.status === "active" &&
      session.cli === cli &&
      sessionWorkspaceMatches(session.workspaceId, workspaceHash),
  );
  if (active) return { status: "resolved", session: active };
  return { status: "pending" };
}

function sessionWorkspaceMatches(workspaceId: string, workspaceHash: string): boolean {
  return workspaceId === workspaceHash || workspaceId.endsWith(`/${workspaceHash}`);
}
