import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { OverrideMutateResponse, ToggleResponse } from "../api";
import {
  clearOverrides as apiClear,
  patchOverrides as apiPatch,
  toggleOverrides as apiToggle,
  fetchOverrides,
} from "../api";
import type { InternalRequest, Override, OverrideAudit, OverrideScope } from "../types";

export interface UseOverridesResult {
  overrides: Override[];
  enabled: boolean;
  audit: OverrideAudit | null;
  curatedIr: InternalRequest | null;
  upsert: (overrides: Override[]) => Promise<OverrideMutateResponse>;
  clear: () => Promise<void>;
  toggle: () => Promise<ToggleResponse>;
}

function overridesQueryKey(scope?: OverrideScope | null) {
  return ["overrides", scope?.run_id ?? null, scope?.track_id ?? null] as const;
}

export function useOverrides(scope?: OverrideScope | null): UseOverridesResult {
  const queryClient = useQueryClient();
  const queryKey = overridesQueryKey(scope);
  const invalidate = () => queryClient.invalidateQueries({ queryKey });

  const { data } = useQuery({
    queryKey,
    queryFn: () => fetchOverrides(scope),
  });

  const patchMutation = useMutation({
    mutationFn: (overrides: Override[]) => apiPatch(overrides, scope),
    onSuccess: (resp) => {
      queryClient.setQueryData(queryKey, {
        overrides: resp.overrides,
        enabled: resp.enabled,
      });
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => apiClear(scope),
    onSuccess: invalidate,
  });

  const toggleMutation = useMutation({
    mutationFn: () => apiToggle(scope),
    onSuccess: (resp) => {
      queryClient.setQueryData(
        queryKey,
        (prev: { overrides: Override[]; enabled: boolean } | undefined) => ({
          overrides: prev?.overrides ?? [],
          enabled: resp.enabled,
        }),
      );
    },
  });

  return {
    overrides: data?.overrides ?? [],
    enabled: data?.enabled ?? true,
    audit: patchMutation.data?.audit ?? toggleMutation.data?.audit ?? null,
    curatedIr: patchMutation.data?.curated_ir ?? toggleMutation.data?.curated_ir ?? null,
    upsert: (overrides: Override[]) => patchMutation.mutateAsync(overrides),
    clear: async () => {
      await clearMutation.mutateAsync();
    },
    toggle: () => toggleMutation.mutateAsync(),
  };
}
