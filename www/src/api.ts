import type {
  BreakpointStatusDetail,
  ExchangeDetail,
  IndexEntry,
  InternalRequest,
  Override,
  OverrideAudit,
  OverrideScope,
  PausedFlow,
} from "./types";

export const MAX_ENTRIES = 500;

async function throwWithDetail(res: Response, fallback: string): Promise<never> {
  let detail: string | null = null;
  try {
    const data = (await res.json()) as { detail?: string };
    detail = typeof data.detail === "string" ? data.detail : null;
  } catch {}
  if (detail) {
    throw new Error(detail);
  }
  throw new Error(fallback);
}

export async function fetchExchanges(
  limit = 50,
  offset = 0,
  includeHistory = false,
): Promise<IndexEntry[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (includeHistory) {
    params.set("include_history", "true");
  }
  const res = await fetch(`/api/exchanges?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch exchanges: ${res.status}`);
  }
  return (await res.json()) as IndexEntry[];
}

export async function fetchExchange(id: string): Promise<ExchangeDetail> {
  const res = await fetch(`/api/exchanges/${encodeURIComponent(id)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch exchange ${id}: ${res.status}`);
  }
  return (await res.json()) as ExchangeDetail;
}

export type PipelineTokensReason =
  | "counter_unavailable"
  | "no_auth"
  | "artifact_missing"
  | "counter_failed"
  | "unsupported_provider";

export interface PipelineTokensResponse {
  tokens_before: number | null;
  tokens_after: number | null;
  /**
   * Null on success (both sides real) or cached hit. One of four
   * known codes on a degraded path — see the docstring on the
   * Python-side `PipelineTokensResponse` model at
   * `api/src/manicure/api/v1/exchanges.py` for what each means.
   * We don't render this today; the chars fallback is good enough.
   */
  reason: PipelineTokensReason | null;
}

/**
 * Lazy pipeline-token recount. Only meaningful for rows where the index
 * carries null tokens (pre-counter captures or first-stamp failures).
 * Server short-circuits to the cached values when the row is already
 * stamped, so calling this on a fresh row is cheap. On failure or when
 * the server has no auth to replay, both fields are null and the caller
 * should keep displaying chars.
 */
export async function fetchPipelineTokens(id: string): Promise<PipelineTokensResponse> {
  const res = await fetch(`/api/exchanges/${encodeURIComponent(id)}/pipeline_tokens`);
  if (!res.ok) {
    throw new Error(`Failed to fetch pipeline tokens for ${id}: ${res.status}`);
  }
  return (await res.json()) as PipelineTokensResponse;
}

// ── Override endpoints ────────────────────────────────────────────

export interface OverrideListResponse {
  overrides: Override[];
  enabled: boolean;
}

export interface OverrideMutateResponse {
  overrides: Override[];
  enabled: boolean;
  audit: OverrideAudit | null;
  curated_ir: InternalRequest | null;
}

export interface ToggleResponse {
  enabled: boolean;
  audit: OverrideAudit | null;
  curated_ir: InternalRequest | null;
}

function overrideScopeQuery(scope?: OverrideScope | null): string {
  const params = new URLSearchParams();
  if (scope?.run_id) params.set("run_id", scope.run_id);
  if (scope?.track_id) params.set("track_id", scope.track_id);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function fetchOverrides(scope?: OverrideScope | null): Promise<OverrideListResponse> {
  const res = await fetch(`/api/overrides${overrideScopeQuery(scope)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch overrides: ${res.status}`);
  }
  return (await res.json()) as OverrideListResponse;
}

export async function patchOverrides(
  overrides: Override[],
  scope?: OverrideScope | null,
): Promise<OverrideMutateResponse> {
  const res = await fetch(`/api/overrides${overrideScopeQuery(scope)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
  if (!res.ok) {
    throw new Error(`Failed to patch overrides: ${res.status}`);
  }
  return (await res.json()) as OverrideMutateResponse;
}

export async function clearOverrides(scope?: OverrideScope | null): Promise<void> {
  const res = await fetch(`/api/overrides${overrideScopeQuery(scope)}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Failed to clear overrides: ${res.status}`);
  }
}

export async function toggleOverrides(scope?: OverrideScope | null): Promise<ToggleResponse> {
  const res = await fetch(`/api/overrides/toggle${overrideScopeQuery(scope)}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Failed to toggle overrides: ${res.status}`);
  }
  return (await res.json()) as ToggleResponse;
}

// ── Breakpoint endpoints ──────────────────────────────────────────

export async function fetchBreakpointStatus(): Promise<BreakpointStatusDetail> {
  const res = await fetch("/api/breakpoint/status");
  if (!res.ok) {
    throw new Error(`Failed to fetch breakpoint status: ${res.status}`);
  }
  return (await res.json()) as BreakpointStatusDetail;
}

export async function armBreakpoint(): Promise<void> {
  const res = await fetch("/api/breakpoint/arm", { method: "POST" });
  if (!res.ok) {
    throw new Error(`Failed to arm breakpoint: ${res.status}`);
  }
}

export async function disarmBreakpoint(): Promise<void> {
  const res = await fetch("/api/breakpoint/disarm", { method: "POST" });
  if (!res.ok) {
    throw new Error(`Failed to disarm breakpoint: ${res.status}`);
  }
}

export async function releaseFlow(flowId: string, ir: InternalRequest): Promise<void> {
  const res = await fetch(`/api/breakpoint/release/${encodeURIComponent(flowId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ir),
  });
  if (!res.ok) {
    await throwWithDetail(res, `Failed to release flow ${flowId}: ${res.status}`);
  }
}

export async function releaseFlowUnmodified(flowId: string): Promise<void> {
  const res = await fetch(`/api/breakpoint/release-unmodified/${encodeURIComponent(flowId)}`, {
    method: "POST",
  });
  if (!res.ok) {
    await throwWithDetail(res, `Failed to release flow ${flowId}: ${res.status}`);
  }
}

export async function dropFlow(flowId: string): Promise<void> {
  const res = await fetch(`/api/breakpoint/drop/${encodeURIComponent(flowId)}`, {
    method: "POST",
  });
  if (!res.ok) {
    await throwWithDetail(res, `Failed to drop flow ${flowId}: ${res.status}`);
  }
}

export interface ReauditResponse {
  audit: OverrideAudit;
  curated_ir: InternalRequest;
  tokens_before: number | null;
}

export async function reauditFlow(flowId: string): Promise<ReauditResponse> {
  const res = await fetch(`/api/breakpoint/re-audit/${encodeURIComponent(flowId)}`, {
    method: "POST",
  });
  if (!res.ok) {
    await throwWithDetail(res, `Failed to re-audit flow ${flowId}: ${res.status}`);
  }
  return (await res.json()) as ReauditResponse;
}

export async function fetchPausedFlowDetail(flowId: string): Promise<PausedFlow> {
  const res = await fetch(`/api/breakpoint/paused/${encodeURIComponent(flowId)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch paused flow ${flowId}: ${res.status}`);
  }
  return (await res.json()) as PausedFlow;
}

// ── Meta endpoint ─────────────────────────────────────────────────

export interface Meta {
  cwd: string;
  workspaceId: string;
  runId?: string | null;
}

/**
 * Resolve the backend's cwd and workspace id. The cwd is fixed for the
 * lifetime of the process (set by `manicure start`), so the frontend
 * caches this with an infinite staleTime and prefetches at app mount.
 *
 * `workspaceId` is an opaque stable string the apply-at-intercept
 * pipeline will use to scope overlays; the UI does not read it today.
 */
export async function fetchMeta(): Promise<Meta> {
  const res = await fetch("/api/meta");
  if (!res.ok) {
    throw new Error(`Failed to fetch meta: ${res.status}`);
  }
  const raw = (await res.json()) as {
    cwd: string;
    workspace_id: string;
    run_id: string | null;
  };
  return { cwd: raw.cwd, workspaceId: raw.workspace_id, runId: raw.run_id };
}
