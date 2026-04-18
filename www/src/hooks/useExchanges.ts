import { useQuery } from "@tanstack/react-query";
import { fetchExchanges, MAX_ENTRIES } from "../api";
import type { IndexEntry } from "../types";

export function useExchanges(
  includeHistory: boolean,
  enabled = true,
): {
  exchanges: IndexEntry[];
  isLoading: boolean;
} {
  const { data: exchanges = [], isLoading } = useQuery({
    queryKey: ["exchanges", includeHistory],
    queryFn: () =>
      fetchExchanges(MAX_ENTRIES, 0, includeHistory).then((data) =>
        data.slice().reverse().slice(0, MAX_ENTRIES),
      ),
    staleTime: Number.POSITIVE_INFINITY, // SSE keeps data fresh via setQueryData
    enabled,
  });
  return { exchanges, isLoading };
}
