import { requestApiJson } from "../../api";

export type SessionPurpose =
  | "user"
  | "continuation"
  | "internal_summary"
  | "internal_indexing"
  | "internal_eval"
  | "system_maintenance";

export type SessionVisibility = "user_visible" | "hidden" | "diagnostic";

export interface SessionLineage {
  parentSessionId: string | null;
  forkedAtSeq: number | null;
  forkedAtTurn: number | null;
}

export interface SessionSummary {
  sessionId: string;
  workspaceId: string;
  title: string | null;
  status: string;
  provider: string;
  harness: string;
  createdAt: string;
  lastActivityAt: string;
  purpose: SessionPurpose;
  visibility: SessionVisibility;
  lineage: SessionLineage;
  turnCount: number;
  inheritedTurnCount: number;
  lastMessagePreview: string | null;
}

export interface SessionListResponse {
  items: SessionSummary[];
  nextCursor: string | null;
}

export interface SessionListFilters {
  owner: "local";
  workspaceHash?: string | null;
  purpose?: SessionPurpose | null;
  visibility?: SessionVisibility | null;
  includeInternal?: boolean;
  harness?: string | null;
  limit?: number;
  cursor?: string | null;
}

const DEFAULT_LIMIT = 50;

export async function listSessions(filters: SessionListFilters): Promise<SessionSummary[]> {
  const response = await requestApiJson<SessionListResponse>(
    sessionsPath(filters),
    "Failed to fetch sessions",
  );
  const harness = filters.harness;
  return harness ? response.items.filter((session) => session.harness === harness) : response.items;
}

export function sessionsPath(filters: SessionListFilters): string {
  const params = new URLSearchParams({
    owner: filters.owner,
    limit: String(filters.limit ?? DEFAULT_LIMIT),
  });
  appendParam(params, "workspaceId", filters.workspaceHash);
  appendParam(params, "purpose", filters.purpose);
  appendParam(params, "visibility", filters.visibility);
  appendBooleanParam(params, "includeInternal", filters.includeInternal);
  appendParam(params, "cursor", filters.cursor);
  return `/v1/sessions?${params.toString()}`;
}

function appendParam(params: URLSearchParams, key: string, value: string | null | undefined): void {
  if (value && value.length > 0) params.set(key, value);
}

function appendBooleanParam(
  params: URLSearchParams,
  key: string,
  value: boolean | null | undefined,
): void {
  if (value !== null && value !== undefined) params.set(key, String(value));
}
