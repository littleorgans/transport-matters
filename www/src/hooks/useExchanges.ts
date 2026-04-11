import { useQuery } from "@tanstack/react-query";
import { fetchExchanges } from "../api";
import type { IndexEntry } from "../types";

const MAX_ENTRIES = 500;

export function useExchanges(): { exchanges: IndexEntry[] } {
  const { data: exchanges = [] } = useQuery({
    queryKey: ["exchanges"],
    queryFn: () =>
      fetchExchanges(MAX_ENTRIES, 0).then((data) => data.slice().reverse().slice(0, MAX_ENTRIES)),
    staleTime: Number.POSITIVE_INFINITY, // SSE keeps data fresh via setQueryData
  });
  return { exchanges };
}
