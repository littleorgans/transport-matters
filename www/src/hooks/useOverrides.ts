import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { OverrideMutateResponse, ToggleResponse } from "../api";
import {
  clearOverrides as apiClear,
  patchOverrides as apiPatch,
  toggleOverrides as apiToggle,
  fetchOverrides,
} from "../api";
import type { InternalRequest, Override, OverrideAudit } from "../types";

export interface UseOverridesResult {
  overrides: Override[];
  enabled: boolean;
  audit: OverrideAudit | null;
  curatedIr: InternalRequest | null;
  upsert: (overrides: Override[]) => Promise<OverrideMutateResponse>;
  clear: () => Promise<void>;
  toggle: () => Promise<ToggleResponse>;
}

export function useOverrides(): UseOverridesResult {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["overrides"] });

  const { data } = useQuery({
    queryKey: ["overrides"],
    queryFn: fetchOverrides,
  });

  const patchMutation = useMutation({
    mutationFn: apiPatch,
    onSuccess: (resp) => {
      queryClient.setQueryData(["overrides"], {
        overrides: resp.overrides,
        enabled: resp.enabled,
      });
    },
  });

  const clearMutation = useMutation({
    mutationFn: apiClear,
    onSuccess: invalidate,
  });

  const toggleMutation = useMutation({
    mutationFn: apiToggle,
    onSuccess: (resp) => {
      queryClient.setQueryData(
        ["overrides"],
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
