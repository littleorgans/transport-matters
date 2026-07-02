import { requestApiJson, requestApiVoid } from "@tm/core";
import type { PausedFlow } from "@tm/core/types/exchanges";
import type { InternalRequest } from "@tm/core/types/ir";
import type { Override, OverrideAudit, OverrideScope } from "@tm/core/types/overrides";
import type { BreakpointStatusDetail } from "./types/breakpoints";

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
  return requestApiJson<OverrideListResponse>(
    `/api/overrides${overrideScopeQuery(scope)}`,
    "Failed to fetch overrides",
  );
}

export async function patchOverrides(
  overrides: Override[],
  scope?: OverrideScope | null,
): Promise<OverrideMutateResponse> {
  return requestApiJson<OverrideMutateResponse>(
    `/api/overrides${overrideScopeQuery(scope)}`,
    "Failed to patch overrides",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides }),
    },
  );
}

export async function clearOverrides(scope?: OverrideScope | null): Promise<void> {
  await requestApiVoid(`/api/overrides${overrideScopeQuery(scope)}`, "Failed to clear overrides", {
    method: "DELETE",
  });
}

export async function toggleOverrides(scope?: OverrideScope | null): Promise<ToggleResponse> {
  return requestApiJson<ToggleResponse>(
    `/api/overrides/toggle${overrideScopeQuery(scope)}`,
    "Failed to toggle overrides",
    {
      method: "POST",
    },
  );
}

// ── Breakpoint endpoints ──────────────────────────────────────────

export async function fetchBreakpointStatus(): Promise<BreakpointStatusDetail> {
  return requestApiJson<BreakpointStatusDetail>(
    "/api/breakpoint/status",
    "Failed to fetch breakpoint status",
  );
}

export async function armBreakpoint(): Promise<void> {
  await requestApiVoid("/api/breakpoint/arm", "Failed to arm breakpoint", { method: "POST" });
}

export async function disarmBreakpoint(): Promise<void> {
  await requestApiVoid("/api/breakpoint/disarm", "Failed to disarm breakpoint", { method: "POST" });
}

export async function releaseFlow(flowId: string, ir: InternalRequest): Promise<void> {
  await requestApiVoid(
    `/api/breakpoint/release/${encodeURIComponent(flowId)}`,
    `Failed to release flow ${flowId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ir),
    },
    { detailAware: true },
  );
}

export async function releaseFlowUnmodified(flowId: string): Promise<void> {
  await requestApiVoid(
    `/api/breakpoint/release-unmodified/${encodeURIComponent(flowId)}`,
    `Failed to release flow ${flowId}`,
    {
      method: "POST",
    },
    { detailAware: true },
  );
}

export async function dropFlow(flowId: string): Promise<void> {
  await requestApiVoid(
    `/api/breakpoint/drop/${encodeURIComponent(flowId)}`,
    `Failed to drop flow ${flowId}`,
    {
      method: "POST",
    },
    { detailAware: true },
  );
}

export interface ReauditResponse {
  audit: OverrideAudit;
  curated_ir: InternalRequest;
  tokens_before: number | null;
}

export async function reauditFlow(flowId: string): Promise<ReauditResponse> {
  return requestApiJson<ReauditResponse>(
    `/api/breakpoint/re-audit/${encodeURIComponent(flowId)}`,
    `Failed to re-audit flow ${flowId}`,
    {
      method: "POST",
    },
    { detailAware: true },
  );
}

export async function fetchPausedFlowDetail(flowId: string): Promise<PausedFlow> {
  return requestApiJson<PausedFlow>(
    `/api/breakpoint/paused/${encodeURIComponent(flowId)}`,
    `Failed to fetch paused flow ${flowId}`,
  );
}
