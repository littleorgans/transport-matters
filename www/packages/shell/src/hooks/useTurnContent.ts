import { useQuery } from "@tanstack/react-query";
import { fetchTurnContent } from "../api";
import { turnContentKey } from "../lib/queryKeys";
import type { TurnContent } from "../types";

export function useTurnContent(runId: string | null, id: string) {
  return useQuery<TurnContent>({
    queryKey: turnContentKey(runId, id),
    queryFn: () => fetchTurnContent(runId ?? "", id),
    enabled: runId !== null && id.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
