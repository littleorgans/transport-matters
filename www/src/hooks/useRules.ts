import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRule as apiCreateRule,
  deleteRule as apiDeleteRule,
  fetchRules,
  patchRule,
} from "../api";
import type { CreateRuleBody, Rule } from "../types";

export function useRules(): {
  rules: Rule[];
  error: Error | null;
  createRule: (body: CreateRuleBody) => Promise<void>;
  toggleRule: (id: string, enabled: boolean) => Promise<void>;
  deleteRule: (id: string) => Promise<void>;
} {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["rules"] });

  const { data: rules = [], error } = useQuery({
    queryKey: ["rules"],
    queryFn: fetchRules,
  });

  const createMutation = useMutation({
    mutationFn: apiCreateRule,
    onSuccess: invalidate,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => patchRule(id, { enabled }),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: apiDeleteRule,
    onSuccess: invalidate,
  });

  return {
    rules,
    error: error instanceof Error ? error : null,
    createRule: async (body: CreateRuleBody) => {
      await createMutation.mutateAsync(body);
    },
    toggleRule: async (id: string, enabled: boolean) => {
      await toggleMutation.mutateAsync({ id, enabled });
    },
    deleteRule: (id: string) => deleteMutation.mutateAsync(id),
  };
}
