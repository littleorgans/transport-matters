import { useQuery } from "@tanstack/react-query";
import { launchSessionKey } from "@tm/core";
import { resolveLaunchSession } from "../api/launchResolution";
import { listSessions } from "../api/sessionClient";
import type { CanvasLaunchContext } from "../route";

const LAUNCH_POLL_MS = 1_000;

export function useLaunchSession(launch: CanvasLaunchContext) {
  const enabled = launch.workspaceHash !== null && launch.harness !== null;
  return useQuery({
    enabled,
    queryKey: launchSessionKey(launch),
    queryFn: async () => {
      const sessions = await listSessions({
        owner: "local",
        workspaceHash: launch.workspaceHash,
        harness: launch.harness,
        limit: 50,
      });
      return resolveLaunchSession(sessions, launch);
    },
    refetchInterval: (query) => (query.state.data?.status === "resolved" ? false : LAUNCH_POLL_MS),
  });
}
