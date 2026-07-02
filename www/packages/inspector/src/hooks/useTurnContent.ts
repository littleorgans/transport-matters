import { useQuery } from "@tanstack/react-query";
import { fetchTurnContent, turnContentKey } from "@tm/core";
import type { TurnContent } from "@tm/core/types/exchanges";

export function useTurnContent(runId: string | null, id: string) {
  return useQuery<TurnContent>({
    queryKey: turnContentKey(runId, id),
    queryFn: () => fetchTurnContent(runId ?? "", id),
    enabled: runId !== null && id.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
