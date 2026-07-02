import { requestApiJson } from "@tm/core";

// Resource content response union. Mirrors the shipped slice-7 endpoint
// (api/src/transport_matters/session/resource_content_models.py). The endpoint's
// models extend TimelineModel, whose `alias_generator=_to_camel` serializes the
// wire in CAMELCASE (verified by api/.../test_session_resource_content.py, which
// asserts payload["mediaType"], payload["tooLarge"], payload["exchangeId"], ...).
// These interfaces therefore use camelCase to match the actual wire.

/** The six truths a resource pane can be showing. Canonical, backend-owned. */
export type ResourceContentProvenance =
  | "current"
  | "captured"
  | "inline-artifact"
  | "structured-wire"
  | "raw-provider-debug"
  | "native-record";

export type MissingResourceReason =
  | "not-found"
  | "outside-workspace"
  | "permission-denied"
  | "too-large"
  | "debug-unavailable"
  | "unsupported"
  | "uncorrelated";

export type InitialExchangeView = "request" | "response" | "events" | "diagnostics";

export interface ResourceContentBase {
  id: string;
  title: string;
  mediaType: string | null;
  contentLength: number | null;
  contentProvenance: ResourceContentProvenance;
  provenance: Record<string, unknown>;
}

export interface TextRange {
  start: number;
  end: number;
  total: number;
}

export interface TextContentResponse extends ResourceContentBase {
  kind: "text";
  text: string;
  encoding: "utf-8";
  range: TextRange | null;
  truncated: boolean;
}

export interface ImageContentResponse extends ResourceContentBase {
  kind: "image";
  url: string | null;
  bytesBase64: string | null;
  width: number | null;
  height: number | null;
  alt: string | null;
}

export interface BinaryContentResponse extends ResourceContentBase {
  kind: "binary";
  downloadUrl: string | null;
  sha256: string | null;
  tooLarge: boolean;
}

export interface JsonContentResponse extends ResourceContentBase {
  kind: "json";
  value: unknown;
  text: string | null;
  truncated: boolean;
}

export interface ExchangeRedirectResponse extends ResourceContentBase {
  kind: "exchange-redirect";
  runId: string;
  exchangeId: string;
  route: string;
  initialView: InitialExchangeView | null;
}

export interface MissingResourceResponse extends ResourceContentBase {
  kind: "missing";
  reason: MissingResourceReason;
  message: string;
  retryable: boolean;
}

export type ResourceContentResponse =
  | TextContentResponse
  | ImageContentResponse
  | BinaryContentResponse
  | JsonContentResponse
  | ExchangeRedirectResponse
  | MissingResourceResponse;

export interface ResourceContentFilters {
  sessionId: string;
  resourceId: string;
  owner: "local";
  rangeStart?: number | null;
  rangeEnd?: number | null;
  includeDebug?: boolean;
}

export async function loadResourceContent(
  filters: ResourceContentFilters,
): Promise<ResourceContentResponse> {
  return requestApiJson<ResourceContentResponse>(
    resourceContentPath(filters),
    "Failed to fetch resource content",
  );
}

export function localFileContentPath(path: string): string {
  return `/api/local-file?path=${encodeURIComponent(path)}`;
}

export async function loadLocalFileContent(path: string): Promise<ResourceContentResponse> {
  return requestApiJson<ResourceContentResponse>(
    localFileContentPath(path),
    "Failed to fetch local file",
  );
}

export function resourceContentPath(filters: ResourceContentFilters): string {
  const params = new URLSearchParams({ owner: filters.owner });
  appendNumberParam(params, "range_start", filters.rangeStart);
  appendNumberParam(params, "range_end", filters.rangeEnd);
  if (filters.includeDebug) params.set("include_debug", "true");
  return `/v1/sessions/${encodeURIComponent(filters.sessionId)}/resources/${encodeURIComponent(
    filters.resourceId,
  )}?${params.toString()}`;
}

function appendNumberParam(
  params: URLSearchParams,
  key: string,
  value: number | null | undefined,
): void {
  if (value !== null && value !== undefined) params.set(key, String(value));
}
