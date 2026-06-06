import { requestApiJson } from "../../api";

export interface SessionSummary {
  session_id: string;
  provider: string;
  cli: string | null;
  run_id: string;
  cwd: string;
  workspace_slug: string;
  workspace_hash: string;
  native_session_id: string | null;
  minted: boolean;
  source_descriptor: Record<string, unknown> | null;
  home_dir: string | null;
  owner: string;
  status: string;
  title: string | null;
  parent_session_id: string | null;
  forked_at_seq: number | null;
  started_at: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionListFilters {
  owner: "local";
  workspaceHash?: string | null;
  provider?: string | null;
  cli?: string | null;
  status?: "active" | "completed" | "archived" | null;
  limit?: number;
  offset?: number;
}

const DEFAULT_LIMIT = 50;
const DEFAULT_OFFSET = 0;

export async function listSessions(filters: SessionListFilters): Promise<SessionSummary[]> {
  return requestApiJson<SessionSummary[]>(sessionsPath(filters), "Failed to fetch sessions");
}

export function sessionsPath(filters: SessionListFilters): string {
  const params = new URLSearchParams({
    owner: filters.owner,
    limit: String(filters.limit ?? DEFAULT_LIMIT),
    offset: String(filters.offset ?? DEFAULT_OFFSET),
  });
  appendParam(params, "workspace_hash", filters.workspaceHash);
  appendParam(params, "provider", filters.provider);
  appendParam(params, "cli", filters.cli);
  appendParam(params, "status", filters.status);
  return `/api/sessions?${params.toString()}`;
}

function appendParam(params: URLSearchParams, key: string, value: string | null | undefined): void {
  if (value && value.length > 0) params.set(key, value);
}
