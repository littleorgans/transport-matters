import { apiUrl, requestApiJson } from "../../api";

export interface SessionEventView {
  session_id: string;
  seq: number;
  kind: string;
  native_turn_id: string | null;
  parent_native_id: string | null;
  parent_seq: number | null;
  run_id: string;
  provider: string;
  cli: string;
  role: string | null;
  is_sidechain: boolean;
  ts: string | null;
  model: string | null;
  ir: Record<string, unknown> | null;
  source_path: string | null;
  source_line: number | null;
  search_text: string | null;
  created_at: string | null;
}

export interface SessionEventListResponse {
  events: SessionEventView[];
  next_from_seq: number | null;
}

export interface SessionEventsFilters {
  sessionId: string;
  owner: "local";
  fromSeq?: number | null;
  toSeq?: number | null;
  limit?: number;
}

const DEFAULT_EVENT_LIMIT = 500;

export async function listSessionEvents(
  filters: SessionEventsFilters,
): Promise<SessionEventListResponse> {
  return requestApiJson<SessionEventListResponse>(
    sessionEventsPath(filters),
    "Failed to fetch session events",
  );
}

export function sessionEventsPath(filters: SessionEventsFilters): string {
  const params = new URLSearchParams({
    owner: filters.owner,
    limit: String(filters.limit ?? DEFAULT_EVENT_LIMIT),
  });
  appendNumberParam(params, "from_seq", filters.fromSeq);
  appendNumberParam(params, "to_seq", filters.toSeq);
  return `/api/sessions/${encodeURIComponent(filters.sessionId)}/events?${params.toString()}`;
}

export function sessionEventsStreamUrl(
  sessionId: string,
  owner: "local",
  lastSeq: number,
  baseUrl?: string,
): string {
  const params = new URLSearchParams({ owner, last_seq: String(lastSeq) });
  return apiUrl(
    `/api/sessions/${encodeURIComponent(sessionId)}/events/stream?${params.toString()}`,
    baseUrl,
  );
}

function appendNumberParam(
  params: URLSearchParams,
  key: string,
  value: number | null | undefined,
): void {
  if (value !== null && value !== undefined) params.set(key, String(value));
}
