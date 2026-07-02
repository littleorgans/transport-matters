import { apiUrl, requestApiJson } from "@tm/core";

export interface TranscriptTextPart {
  type: "text";
  text: string;
}

export type TranscriptEventBody =
  | { kind: "user"; parts: TranscriptTextPart[] }
  | { kind: "assistant"; parts: TranscriptTextPart[] }
  | { kind: "tool_use"; toolName: string | null; input: unknown }
  | { kind: "tool_result"; toolName: string | null; output: unknown; isError: boolean }
  | { kind: "wire_injected"; label: string; parts: TranscriptTextPart[] };

export interface TranscriptResourceRef {
  id: string;
  kind: string;
  label?: string | null;
}

export interface SessionEventView {
  seq: number;
  turnIndex: number | null;
  kind: string;
  role: string | null;
  ts: string | null;
  body: TranscriptEventBody;
  nativePayload: Record<string, unknown> | null;
  resourceRefs: TranscriptResourceRef[];
}

export interface SessionEventListResponse {
  events: SessionEventView[];
  nextFromSeq: number | null;
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
  return `/v1/sessions/${encodeURIComponent(filters.sessionId)}/events?${params.toString()}`;
}

export function sessionEventsStreamUrl(
  sessionId: string,
  owner: "local",
  lastSeq: number,
  baseUrl?: string,
): string {
  const params = new URLSearchParams({ owner, last_seq: String(lastSeq) });
  return apiUrl(
    `/v1/sessions/${encodeURIComponent(sessionId)}/events/stream?${params.toString()}`,
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
