import type { SessionSummary } from "../api/sessionClient";
import { useSessions } from "../hooks/useSessions";
import { deriveFetchStatus, type FetchStatus } from "./commandModel";

export interface SessionHistoryResult {
  sessions: SessionSummary[];
  status: FetchStatus;
  retry: () => void;
}

/**
 * Fetches captured sessions for the Sessions launcher scope and maps the query
 * into the four-state contract. Scoped to the current canvas workspace (like the
 * shipped session picker) and sticky like the specialist fleet: gated on "the
 * palette has been opened" so a never-opened command center never hits the
 * endpoint. A failed fetch degrades to the scope's error/retry rows; it never
 * blocks a spawn.
 */
export function useSessionHistory(
  workspaceHash: string | null,
  enabled = true,
): SessionHistoryResult {
  const query = useSessions({ owner: "local", workspaceHash, limit: 50 }, enabled);
  return {
    sessions: query.data ?? [],
    status: deriveFetchStatus(query.isError, query.data),
    retry: () => {
      void query.refetch();
    },
  };
}
