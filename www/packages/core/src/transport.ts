import type { CapabilitiesResponse, HarnessDescriptor, HarnessName } from "./types/capabilities";
import type { ExchangeDetail, IndexEntry, TurnContent } from "./types/exchanges";
import type { RuntimeTemplateSummary, RuntimeTemplatesResponse } from "./types/runtimeTemplates";

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

export interface RequestApiOptions {
  /**
   * Surface the backend's `detail` payload as the error message on non-OK
   * responses instead of the generic fallback. Product mutation endpoints
   * (breakpoint release, run spawn) opt in so operators see the real cause.
   */
  detailAware?: boolean;
}

async function ensureOkResponse(
  res: Response,
  fallback: string,
  options: RequestApiOptions,
): Promise<void> {
  if (res.ok) return;
  const message = `${fallback}: ${res.status}`;
  if (options.detailAware) {
    await throwWithDetail(res, message);
  }
  throw new Error(message);
}

export async function requestApiJson<T>(
  path: string,
  fallback: string,
  init?: RequestInit,
  options: RequestApiOptions = {},
): Promise<T> {
  const res = await apiTransport.request(path, init);
  await ensureOkResponse(res, fallback, options);
  return (await res.json()) as T;
}

export async function requestApiVoid(
  path: string,
  fallback: string,
  init?: RequestInit,
  options: RequestApiOptions = {},
): Promise<void> {
  await ensureOkResponse(await apiTransport.request(path, init), fallback, options);
}

export async function fetchExchanges(runId: string, limit = 50, offset = 0): Promise<IndexEntry[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return requestApiJson<IndexEntry[]>(
    `/v1/runs/${encodeURIComponent(runId)}/exchanges?${params.toString()}`,
    "Failed to fetch exchanges",
  );
}

export async function fetchExchange(runId: string, id: string): Promise<ExchangeDetail> {
  return requestApiJson<ExchangeDetail>(
    `/v1/runs/${encodeURIComponent(runId)}/exchanges/${encodeURIComponent(id)}`,
    `Failed to fetch exchange ${id}`,
  );
}

export async function fetchTurnContent(runId: string, id: string): Promise<TurnContent> {
  return requestApiJson<TurnContent>(
    `/v1/runs/${encodeURIComponent(runId)}/exchanges/${encodeURIComponent(id)}/turn-content`,
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
export async function fetchPipelineTokens(
  runId: string,
  id: string,
): Promise<PipelineTokensResponse> {
  return requestApiJson<PipelineTokensResponse>(
    `/v1/runs/${encodeURIComponent(runId)}/exchanges/${encodeURIComponent(id)}/pipeline_tokens`,
    `Failed to fetch pipeline tokens for ${id}`,
  );
}

// ── Meta endpoint ─────────────────────────────────────────────────

/**
 * One transcript denylist rule, echoed verbatim from
 * `~/.transport-matters/transcript_denylist.json`. The transcript view applies these as
 * a presentation default: a record whose native payload matches any rule is hidden
 * behind a show-hidden toggle. `equals` omitted (or null) means "hide whenever `path`
 * resolves to a present value". Mirrors `TranscriptDenyRule` in the backend.
 */
export interface TranscriptDenyRule {
  path: string;
  equals?: unknown;
}

export interface Meta {
  channel: string;
  channelBadge: ChannelBadgeMeta | null;
  channelLabel: string;
  cwd: string;
  harnesses: HarnessDescriptor[];
  workspaceId: string;
  runId?: string | null;
  // The launch cwd's resolved Space + primary worktree; the canvas seeds its
  // default spawn target from this. Null when the backend could not resolve one
  // (no/degraded session store).
  spaceId: string | null;
  worktreeId: string | null;
  transcriptDenylist: TranscriptDenyRule[];
}

export interface ChannelBadgeMeta {
  text: string;
  color: "amber";
  hex: string;
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
export async function fetchMeta(runId?: string): Promise<Meta> {
  const path = runId === undefined ? "/api/meta" : `/v1/runs/${encodeURIComponent(runId)}/meta`;
  const raw = await requestApiJson<{
    channel: string;
    channel_badge: ChannelBadgeMeta | null;
    channel_label: string;
    cwd: string;
    harnesses: HarnessDescriptor[];
    workspace_id: string;
    run_id: string | null;
    space_id?: string | null;
    worktree_id?: string | null;
    transcript_denylist?: TranscriptDenyRule[];
  }>(path, "Failed to fetch meta");
  return {
    channel: raw.channel,
    channelBadge: raw.channel_badge,
    channelLabel: raw.channel_label,
    cwd: raw.cwd,
    harnesses: raw.harnesses,
    workspaceId: raw.workspace_id,
    runId: raw.run_id,
    spaceId: raw.space_id ?? null,
    worktreeId: raw.worktree_id ?? null,
    transcriptDenylist: raw.transcript_denylist ?? [],
  };
}

/**
 * Local install state for each managed harness (`claude`, `codex`). The desktop's
 * lab gates its "Spawn" buttons on this so it never offers to launch a harness that
 * is not on PATH. Cheap and stable for a process lifetime, so callers cache it.
 */
export async function fetchCapabilities(): Promise<CapabilitiesResponse> {
  return requestApiJson<CapabilitiesResponse>("/api/capabilities", "Failed to fetch capabilities");
}

// ── Space / Worktree endpoints (detect-only) ──────────────────────

export type SpaceId = string;
export type WorktreeId = string;

/** A launchable path under a Space (a git worktree, or the lone dir of a plain Space). */
export interface WorktreeSummary {
  worktreeId: WorktreeId;
  spaceId: SpaceId;
  /** Worktree root path. Shown as the row subtitle; never emitted as identity. */
  path: string;
  /** Checked-out branch, or null for detached HEAD / a plain directory. */
  branch: string | null;
  /** The repo's primary checkout (vs. a linked worktree). */
  isPrimary: boolean;
  /** Path no longer exists on disk (mirrors the backend `missing` flag, R4). */
  missing: boolean;
}

/** A project/area, with its worktrees inlined for the launcher's single-vs-multi decision. */
export interface SpaceSummary {
  spaceId: SpaceId;
  /** Project/area display label (repo name or plain-dir basename). */
  label: string;
  /** Git repo (0..n linked worktrees) vs. a plain directory (exactly one). */
  kind: "repo" | "plain";
  worktrees: WorktreeSummary[];
}

/** List detected Spaces with their worktrees inlined via `GET /v1/spaces`. */
export async function fetchSpaces(): Promise<SpaceSummary[]> {
  const response = await requestApiJson<{ items?: SpaceSummary[] }>(
    "/v1/spaces",
    "Failed to load spaces",
  );
  // Never resolve to undefined: react-query rejects an undefined query result,
  // and a payload without `items` degrades to "no spaces", not an error.
  return response.items ?? [];
}

/**
 * List a Space's worktrees via `GET /v1/spaces/{id}/worktrees`. `refresh=1`
 * reconciles against `git worktree list` server-side before returning.
 */
export async function fetchWorktrees(spaceId: string, refresh = false): Promise<WorktreeSummary[]> {
  const query = refresh ? "?refresh=1" : "";
  const response = await requestApiJson<{ items?: WorktreeSummary[] }>(
    `/v1/spaces/${encodeURIComponent(spaceId)}/worktrees${query}`,
    "Failed to load worktrees",
  );
  return response.items ?? [];
}

// ── Managed captured run endpoints ────────────────────────────────

/**
 * Spawn a captured managed harness run (real harness executable in a PTY, traffic through the TM
 * reverse proxy) via `POST /v1/runs` and return its `runId`. Create is separate
 * from attach: the pane attaches to the returned run over a WebSocket, so the run
 * survives a detach. `cwd` is an absolute workspace dir; omitting it lets the
 * backend resolve its launch workspace.
 */
export async function createCapturedRun(
  harness: HarnessName,
  // Worktree the run is captured under. REQUIRED by `POST /v1/runs` (the Spaces
  // rekey made worktreeId mandatory; the backend no longer falls back to a launch
  // worktree). Callers resolve it from the canvas default (seeded from
  // `GET /api/meta`'s worktreeId) or an explicit per-spawn target.
  worktreeId?: string,
  // When false the bridge stays silent on the harness OSC color queries
  // (api: osc_color_responder); true is the terminal-faithful default.
  oscColorReplies = true,
  // Named runtime template to launch the harness under. Omitted → byte-for-byte
  // NATIVE launch (today's behaviour). Present → backend resolves the template
  // for this harness (api: CreateRunRequest.runtimeTemplate).
  runtimeTemplate?: string,
  // Bypass all permission checks for this run. Always sent (like oscColorReplies,
  // unlike the optional runtimeTemplate): the backend turns true into
  // `claude --dangerously-skip-permissions` / `codex --yolo`.
  bypassPermissions = false,
): Promise<string> {
  const body = {
    harness,
    ...(worktreeId === undefined ? {} : { worktreeId }),
    oscColorReplies,
    ...(runtimeTemplate === undefined ? {} : { runtimeTemplate }),
    bypassPermissions,
  };
  const response = await requestApiJson<{ run: { runId: string } }>(
    "/v1/runs",
    "Failed to spawn captured run",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    { detailAware: true },
  );
  return response.run.runId;
}

/**
 * List the runtime templates (specialist agents) installable on disk via
 * `GET /v1/runtime-templates`. The Agents launcher enumerates these as rows;
 * a failed fetch degrades to Native-only and never blocks a spawn.
 */
export async function fetchRuntimeTemplates(): Promise<RuntimeTemplateSummary[]> {
  const response = await requestApiJson<RuntimeTemplatesResponse>(
    "/v1/runtime-templates",
    "Failed to load runtime templates",
  );
  return response.items;
}

/** Explicitly terminate a managed run via `POST /v1/runs/{runId}/terminate`. */
export async function terminateRun(runId: string): Promise<void> {
  await requestApiVoid(
    `/v1/runs/${encodeURIComponent(runId)}/terminate`,
    `Failed to terminate run ${runId}`,
    { method: "POST" },
    { detailAware: true },
  );
}

/** Lifecycle of a managed captured run. Mirrors the backend `RunState` enum. */
export type RunState = "STARTING" | "RUNNING" | "TERMINATING" | "TERMINATED" | "EXITED" | "FAILED";
export type RunEndReason = "explicit" | "idle-timeout" | "shutdown" | "deploy-restart";

/**
 * A managed run as the curated B6 surface sees it. Optional fields are omitted by the
 * backend when unset, so they are optional here too.
 */
export interface RunView {
  runId: string;
  spaceId: string;
  worktreeId: string;
  sessionId: string;
  harness: HarnessName;
  state: RunState;
  endReason?: RunEndReason;
  error?: string;
  createdAt: string;
}

/** Optional server-side filters for `listRuns` (`GET /v1/runs?state`). */
export interface RunFilters {
  state?: RunState;
  spaceId?: string;
  worktreeId?: string;
}

export interface RunLookupOptions {
  signal?: AbortSignal;
}

/**
 * List managed runs via `GET /v1/runs`, optionally filtered by state.
 * Read-only: this never spawns a run. The director surface uses it to show live runs
 * an operator can attach to or terminate.
 */
export async function listRuns(filters?: RunFilters): Promise<RunView[]> {
  const query = new URLSearchParams();
  if (filters?.state !== undefined) query.set("state", filters.state);
  // camelCase to match the backend Query aliases (run_routes.py list_runs:
  // alias="spaceId"/"worktreeId"); snake_case keys are silently ignored.
  if (filters?.spaceId !== undefined) query.set("spaceId", filters.spaceId);
  if (filters?.worktreeId !== undefined) query.set("worktreeId", filters.worktreeId);
  const suffix = query.toString();
  const response = await requestApiJson<{ items: RunView[]; nextCursor: string | null }>(
    suffix ? `/v1/runs?${suffix}` : "/v1/runs",
    "Failed to list captured runs",
  );
  return response.items;
}

export async function getRun(
  runId: string,
  options: RunLookupOptions = {},
): Promise<RunView | null> {
  const response = await apiTransport.request(`/v1/runs/${encodeURIComponent(runId)}`, {
    signal: options.signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Failed to get captured run: ${response.status}`);
  }
  const body = (await response.json()) as { run: RunView };
  return body.run;
}
