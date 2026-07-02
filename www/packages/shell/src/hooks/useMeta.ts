import { useQuery } from "@tanstack/react-query";
import { fetchMeta, type Meta } from "../api";

/**
 * Backend meta: resolved cwd and workspace id. Prefetched at app mount
 * (see `main.tsx`) so the value is warm by the time OverlaysView paints.
 *
 * staleTime is Infinity because the backend's cwd is fixed at launch
 * and does not change for the lifetime of the process. One network call
 * per page load, reused for the rest of the session.
 */
export function useMeta(): { meta: Meta | undefined; isLoading: boolean } {
  const { data, isLoading } = useQuery({
    queryKey: ["meta"],
    queryFn: () => fetchMeta(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  return { meta: data, isLoading };
}
