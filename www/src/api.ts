import type {
  BreakpointStatusDetail,
  ExchangeDetail,
  IndexEntry,
  InternalRequest,
  Override,
  OverrideAudit,
  PausedFlow,
} from "./types";

export const MAX_ENTRIES = 500;

export async function fetchExchanges(limit = 50, offset = 0): Promise<IndexEntry[]> {
  const res = await fetch(`/api/exchanges?limit=${limit}&offset=${offset}`);
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
  | "counter_failed";

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

export async function fetchOverrides(): Promise<OverrideListResponse> {
  const res = await fetch("/api/overrides");
  if (!res.ok) {
    throw new Error(`Failed to fetch overrides: ${res.status}`);
  }
  return (await res.json()) as OverrideListResponse;
}

export async function patchOverrides(overrides: Override[]): Promise<OverrideMutateResponse> {
  const res = await fetch("/api/overrides", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
  if (!res.ok) {
    throw new Error(`Failed to patch overrides: ${res.status}`);
  }
  return (await res.json()) as OverrideMutateResponse;
}

export async function clearOverrides(): Promise<void> {
  const res = await fetch("/api/overrides", { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Failed to clear overrides: ${res.status}`);
  }
}

export async function toggleOverrides(): Promise<ToggleResponse> {
  const res = await fetch("/api/overrides/toggle", { method: "POST" });
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
    throw new Error(`Failed to release flow ${flowId}: ${res.status}`);
  }
}

export async function releaseFlowUnmodified(flowId: string): Promise<void> {
  const res = await fetch(`/api/breakpoint/release-unmodified/${encodeURIComponent(flowId)}`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`Failed to release flow ${flowId}: ${res.status}`);
  }
}

export async function dropFlow(flowId: string): Promise<void> {
  const res = await fetch(`/api/breakpoint/drop/${encodeURIComponent(flowId)}`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`Failed to drop flow ${flowId}: ${res.status}`);
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
    throw new Error(`Failed to re-audit flow ${flowId}: ${res.status}`);
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
