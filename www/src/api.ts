import type {
  BreakpointStatusDetail,
  CapabilitiesResponse,
  CliName,
  ExchangeDetail,
  HarnessDescriptor,
  IndexEntry,
  InternalRequest,
  Override,
  OverrideAudit,
  OverrideScope,
  PausedFlow,
  TurnContent,
} from "./types";

export const MAX_ENTRIES = 500;

type ApiFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface ApiTransport {
  request(path: string, init?: RequestInit): Promise<Response>;
}

export interface ApiTransportOptions {
  baseUrl?: string;
  fetcher?: ApiFetch;
}

export function apiUrl(path: string, baseUrl?: string): string {
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

const defaultApiFetch: ApiFetch = (input, init) =>
  init === undefined ? globalThis.fetch(input) : globalThis.fetch(input, init);

export function createApiTransport({
  baseUrl,
  fetcher = defaultApiFetch,
}: ApiTransportOptions = {}): ApiTransport {
  return {
    request(path, init) {
      const url = apiUrl(path, baseUrl);
      return init === undefined ? fetcher(url) : fetcher(url, init);
    },
  };
}

let apiTransport = createApiTransport();

export function setApiTransport(transport: ApiTransport): void {
  apiTransport = transport;
}

export function resetApiTransport(): void {
  apiTransport = createApiTransport();
}

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

async function requestJson<T>(
  path: string,
  init: RequestInit | undefined,
  fallback: string,
  detailAware = false,
): Promise<T> {
  const res = await apiTransport.request(path, init);
  if (!res.ok) {
    const message = `${fallback}: ${res.status}`;
    if (detailAware) {
      await throwWithDetail(res, message);
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function requestApiJson<T>(
  path: string,
  fallback: string,
  init?: RequestInit,
): Promise<T> {
  return requestJson<T>(path, init, fallback);
}

async function requestVoid(
  path: string,
  init: RequestInit | undefined,
  fallback: string,
  detailAware = false,
): Promise<void> {
  const res = await apiTransport.request(path, init);
  if (!res.ok) {
    const message = `${fallback}: ${res.status}`;
    if (detailAware) {
      await throwWithDetail(res, message);
    }
    throw new Error(message);
  }
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
  return requestJson<IndexEntry[]>(
    `/api/exchanges?${params.toString()}`,
    undefined,
    "Failed to fetch exchanges",
  );
}

export async function fetchExchange(id: string): Promise<ExchangeDetail> {
  return requestJson<ExchangeDetail>(
    `/api/exchanges/${encodeURIComponent(id)}`,
    undefined,
    `Failed to fetch exchange ${id}`,
  );
}

export async function fetchTurnContent(id: string): Promise<TurnContent> {
  return requestJson<TurnContent>(
    `/api/exchanges/${encodeURIComponent(id)}/turn-content`,
    undefined,
    `Failed to fetch turn content for ${id}`,
  );
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
   * `api/src/transport_matters/api/v1/exchanges.py` for what each means.
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
  return requestJson<PipelineTokensResponse>(
    `/api/exchanges/${encodeURIComponent(id)}/pipeline_tokens`,
    undefined,
    `Failed to fetch pipeline tokens for ${id}`,
  );
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
  return requestJson<OverrideListResponse>(
    `/api/overrides${overrideScopeQuery(scope)}`,
    undefined,
    "Failed to fetch overrides",
  );
}

export async function patchOverrides(
  overrides: Override[],
  scope?: OverrideScope | null,
): Promise<OverrideMutateResponse> {
  return requestJson<OverrideMutateResponse>(
    `/api/overrides${overrideScopeQuery(scope)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides }),
    },
    "Failed to patch overrides",
  );
}

export async function clearOverrides(scope?: OverrideScope | null): Promise<void> {
  await requestVoid(
    `/api/overrides${overrideScopeQuery(scope)}`,
    {
      method: "DELETE",
    },
    "Failed to clear overrides",
  );
}

export async function toggleOverrides(scope?: OverrideScope | null): Promise<ToggleResponse> {
  return requestJson<ToggleResponse>(
    `/api/overrides/toggle${overrideScopeQuery(scope)}`,
    {
      method: "POST",
    },
    "Failed to toggle overrides",
  );
}

// ── Breakpoint endpoints ──────────────────────────────────────────

export async function fetchBreakpointStatus(): Promise<BreakpointStatusDetail> {
  return requestJson<BreakpointStatusDetail>(
    "/api/breakpoint/status",
    undefined,
    "Failed to fetch breakpoint status",
  );
}

export async function armBreakpoint(): Promise<void> {
  await requestVoid("/api/breakpoint/arm", { method: "POST" }, "Failed to arm breakpoint");
}

export async function disarmBreakpoint(): Promise<void> {
  await requestVoid("/api/breakpoint/disarm", { method: "POST" }, "Failed to disarm breakpoint");
}

export async function releaseFlow(flowId: string, ir: InternalRequest): Promise<void> {
  await requestVoid(
    `/api/breakpoint/release/${encodeURIComponent(flowId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ir),
    },
    `Failed to release flow ${flowId}`,
    true,
  );
}

export async function releaseFlowUnmodified(flowId: string): Promise<void> {
  await requestVoid(
    `/api/breakpoint/release-unmodified/${encodeURIComponent(flowId)}`,
    {
      method: "POST",
    },
    `Failed to release flow ${flowId}`,
    true,
  );
}

export async function dropFlow(flowId: string): Promise<void> {
  await requestVoid(
    `/api/breakpoint/drop/${encodeURIComponent(flowId)}`,
    {
      method: "POST",
    },
    `Failed to drop flow ${flowId}`,
    true,
  );
}

export interface ReauditResponse {
  audit: OverrideAudit;
  curated_ir: InternalRequest;
  tokens_before: number | null;
}

export async function reauditFlow(flowId: string): Promise<ReauditResponse> {
  return requestJson<ReauditResponse>(
    `/api/breakpoint/re-audit/${encodeURIComponent(flowId)}`,
    {
      method: "POST",
    },
    `Failed to re-audit flow ${flowId}`,
    true,
  );
}

export async function fetchPausedFlowDetail(flowId: string): Promise<PausedFlow> {
  return requestJson<PausedFlow>(
    `/api/breakpoint/paused/${encodeURIComponent(flowId)}`,
    undefined,
    `Failed to fetch paused flow ${flowId}`,
  );
}

// ── Meta endpoint ─────────────────────────────────────────────────

export interface Meta {
  cwd: string;
  harnesses: HarnessDescriptor[];
  workspaceId: string;
  runId?: string | null;
}

/**
 * Resolve the backend's cwd, workspace id, and executable harness data. The cwd
 * is fixed for the lifetime of the process (set by `transport-matters start`),
 * so the frontend caches this with an infinite staleTime and prefetches at app
 * mount.
 *
 * `workspaceId` is an opaque stable string the apply-at-intercept
 * pipeline will use to scope overlays; the UI does not read it today. Harness
 * ids describe executable clients separately from captured provider fields.
 */
export async function fetchMeta(): Promise<Meta> {
  const raw = await requestJson<{
    cwd: string;
    harnesses: HarnessDescriptor[];
    workspace_id: string;
    run_id: string | null;
  }>("/api/meta", undefined, "Failed to fetch meta");
  return {
    cwd: raw.cwd,
    harnesses: raw.harnesses,
    workspaceId: raw.workspace_id,
    runId: raw.run_id,
  };
}

/**
 * Local install state for each managed CLI (`claude`, `codex`). The desktop's
 * lab gates its "Spawn" buttons on this so it never offers to launch a CLI that
 * is not on PATH. Cheap and stable for a process lifetime, so callers cache it.
 */
export async function fetchCapabilities(): Promise<CapabilitiesResponse> {
  return requestJson<CapabilitiesResponse>(
    "/api/capabilities",
    undefined,
    "Failed to fetch capabilities",
  );
}

// ── Managed captured run endpoints ────────────────────────────────

/**
 * Spawn a captured managed-CLI run (real CLI in a PTY, traffic through the TM
 * reverse proxy) via `POST /api/runs` and return its `runId`. Create is separate
 * from attach: the pane attaches to the returned run over a WebSocket, so the run
 * survives a detach. `cwd` is an absolute workspace dir; omitting it lets the
 * backend resolve its launch workspace.
 */
export async function createCapturedRun(
  cli: CliName,
  cwd?: string,
  // When false the bridge stays silent on the CLI's OSC color queries
  // (api: osc_color_responder); true is the terminal-faithful default.
  oscColorReplies = true,
): Promise<string> {
  const body = { cli, ...(cwd === undefined ? {} : { cwd }), oscColorReplies };
  const response = await requestJson<{ run: { runId: string } }>(
    "/api/runs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to spawn captured run",
    true,
  );
  return response.run.runId;
}

/** Explicitly stop a managed run via `DELETE /api/runs/{runId}`. */
export async function deleteRun(runId: string): Promise<void> {
  await requestVoid(
    `/api/runs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
    `Failed to stop run ${runId}`,
    true,
  );
}

/** Lifecycle of a managed captured run. Mirrors the backend `RunState` enum. */
export type RunState = "starting" | "running" | "stopping" | "exited" | "failed";

/**
 * A managed run as the director surface sees it: enough to list, attach, and stop a
 * run without the raw bytes. Optional fields are omitted by the backend when unset
 * (`exclude_none`), so they are optional here too. Mirrors the backend `RunViewModel`.
 */
export interface RunView {
  runId: string;
  cli: CliName;
  cwd: string;
  storageDir: string;
  proxyPort: number;
  webPort?: number;
  nativeSessionId?: string;
  state: RunState;
  viewerCount: number;
  createdAt: string;
  startedAt: string;
  updatedAt: string;
  viewerlessSince?: string;
  exitCode?: number;
  stopReason?: string;
  scrollbackBytes: number;
  scrollbackLimitBytes: number;
}

/** Optional server-side filters for `listRuns` (`GET /api/runs?cli&cwd&state`). */
export interface RunFilters {
  cli?: CliName;
  cwd?: string;
  state?: RunState;
}

/**
 * List managed runs via `GET /api/runs`, optionally filtered by cli, cwd, or state.
 * Read-only: this never spawns a run. The director surface uses it to show live runs
 * an operator can attach to or stop.
 */
export async function listRuns(filters?: RunFilters): Promise<RunView[]> {
  const query = new URLSearchParams();
  if (filters?.cli !== undefined) query.set("cli", filters.cli);
  if (filters?.cwd !== undefined) query.set("cwd", filters.cwd);
  if (filters?.state !== undefined) query.set("state", filters.state);
  const suffix = query.toString();
  const response = await requestJson<{ runs: RunView[] }>(
    suffix ? `/api/runs?${suffix}` : "/api/runs",
    undefined,
    "Failed to list captured runs",
  );
  return response.runs;
}
