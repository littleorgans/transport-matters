import { useQuery } from "@tanstack/react-query";
import { sessionEventsKey } from "@tm/core";
import { listSessionEvents, type SessionEventsFilters } from "../api/sessionEvents";

export function useSessionEvents(filters: SessionEventsFilters) {
  return useQuery({
    queryKey: sessionEventsKey(filters),
    queryFn: () => listSessionEvents(filters),
  });
}
