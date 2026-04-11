import type {
  BreakpointStatusDetail,
  CreateRuleBody,
  ExchangeDetail,
  IndexEntry,
  InternalRequest,
  PatchRuleBody,
  PausedFlow,
  Rule,
} from "./types";

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

export async function fetchRules(): Promise<Rule[]> {
  const res = await fetch("/api/rules");
  if (!res.ok) {
    throw new Error(`Failed to fetch rules: ${res.status}`);
  }
  return (await res.json()) as Rule[];
}

export async function createRule(body: CreateRuleBody): Promise<Rule> {
  const res = await fetch("/api/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Failed to create rule: ${res.status}`);
  }
  return (await res.json()) as Rule;
}

export async function patchRule(id: string, body: PatchRuleBody): Promise<Rule> {
  const res = await fetch(`/api/rules/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Failed to patch rule ${id}: ${res.status}`);
  }
  return (await res.json()) as Rule;
}

export async function deleteRule(id: string): Promise<void> {
  const res = await fetch(`/api/rules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Failed to delete rule ${id}: ${res.status}`);
  }
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

export async function fetchPausedFlowDetail(flowId: string): Promise<PausedFlow> {
  const res = await fetch(`/api/breakpoint/paused/${encodeURIComponent(flowId)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch paused flow ${flowId}: ${res.status}`);
  }
  return (await res.json()) as PausedFlow;
}
