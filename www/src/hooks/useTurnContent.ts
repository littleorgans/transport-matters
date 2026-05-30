import { useQuery } from "@tanstack/react-query";
import { fetchTurnContent } from "../api";
import { turnContentKey } from "../lib/queryKeys";
import type { TurnContent } from "../types";

export function useTurnContent(id: string) {
  return useQuery<TurnContent>({
    queryKey: turnContentKey(id),
    queryFn: () => fetchTurnContent(id),
    enabled: id.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
  });
}
