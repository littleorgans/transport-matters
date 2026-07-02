import { useQuery } from "@tanstack/react-query";
import { sessionsKey } from "@tm/core";
import { listSessions, type SessionListFilters } from "../api/sessionClient";

export function useSessions(filters: SessionListFilters, enabled = true) {
  return useQuery({
    queryKey: sessionsKey(filters),
    queryFn: () => listSessions(filters),
    enabled,
  });
}
