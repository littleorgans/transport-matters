import { useQuery } from "@tanstack/react-query";
import { resourceContentKey } from "@tm/core";
import {
  loadResourceContent,
  type ResourceContentFilters,
  type ResourceContentResponse,
} from "../api/resourceContent";

/**
 * Fetch one resource's content for a pane. `retry: false` so a typed missing
 * response (which the endpoint returns with 200) renders immediately and a hard
 * transport error surfaces without backoff churn.
 */
export function useResourceContent(filters: ResourceContentFilters) {
  return useQuery<ResourceContentResponse>({
    queryKey: resourceContentKey(filters),
    queryFn: () => loadResourceContent(filters),
    retry: false,
  });
}
