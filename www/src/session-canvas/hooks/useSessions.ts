import { useQuery } from "@tanstack/react-query";
import { sessionsKey } from "../../lib/queryKeys";
import { listSessions, type SessionListFilters } from "../api/sessionClient";

export function useSessions(filters: SessionListFilters) {
  return useQuery({
    queryKey: sessionsKey(filters),
    queryFn: () => listSessions(filters),
  });
}
