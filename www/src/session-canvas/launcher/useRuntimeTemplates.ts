import { useQuery } from "@tanstack/react-query";
import { fetchRuntimeTemplates } from "../../api";
import type { RuntimeTemplateSummary } from "../../types";
import type { AgentsStatus } from "./commandModel";

export interface RuntimeTemplatesResult {
  templates: RuntimeTemplateSummary[];
  status: AgentsStatus;
  retry: () => void;
}

/**
 * Fetches the specialist fleet for the Agents launcher and maps the query into
 * the four-state contract. Native agents render off the synchronous model, so a
 * pending/failed fetch only ever gates the SPECIALIST rows — it never blocks a
 * spawn. `enabled` is wired to "the palette has been opened", so a never-opened
 * command center never hits the endpoint.
 */
export function useRuntimeTemplates(enabled = true): RuntimeTemplatesResult {
  const query = useQuery({
    queryKey: ["runtime-templates"],
    queryFn: fetchRuntimeTemplates,
    enabled,
    staleTime: 30_000,
  });

  const templates = query.data ?? [];
  const status: AgentsStatus = query.isError
    ? "error"
    : query.data === undefined
      ? "loading"
      : templates.length === 0
        ? "empty"
        : "populated";

  return {
    templates,
    status,
    retry: () => {
      void query.refetch();
    },
  };
}
