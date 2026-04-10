import { useCallback, useEffect, useState } from "react";
import {
  createRule as apiCreateRule,
  deleteRule as apiDeleteRule,
  fetchRules,
  patchRule,
} from "../api";
import type { CreateRuleBody, Rule } from "../types";

export function useRules(): {
  rules: Rule[];
  loading: boolean;
  createRule: (body: CreateRuleBody) => Promise<void>;
  toggleRule: (id: string, enabled: boolean) => Promise<void>;
  deleteRule: (id: string) => Promise<void>;
} {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    fetchRules()
      .then(setRules)
      .catch(() => {
        /* swallow fetch errors on load */
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const createRule = useCallback(
    async (body: CreateRuleBody) => {
      await apiCreateRule(body);
      load();
    },
    [load],
  );

  const toggleRule = useCallback(
    async (id: string, enabled: boolean) => {
      await patchRule(id, { enabled });
      load();
    },
    [load],
  );

  const deleteRule = useCallback(
    async (id: string) => {
      await apiDeleteRule(id);
      load();
    },
    [load],
  );

  return { rules, loading, createRule, toggleRule, deleteRule };
}
