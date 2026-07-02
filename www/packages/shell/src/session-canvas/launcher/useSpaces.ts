import { useQuery } from "@tanstack/react-query";
import { fetchSpaces } from "../../api";
import type { SpaceSummary } from "../../types";

/**
 * Fetches detected Spaces for the Workdir launcher scope. Sticky like the
 * specialist fleet: gated on "the palette has been opened" so a never-opened
 * command center never hits the endpoint. A failed fetch degrades to no spaces
 * (the Workdir scope shows its empty placeholder); it never blocks a spawn.
 */
export function useSpaces(enabled = true): SpaceSummary[] {
  const query = useQuery({
    queryKey: ["spaces"],
    queryFn: fetchSpaces,
    enabled,
    staleTime: 30_000,
  });
  return query.data ?? [];
}
