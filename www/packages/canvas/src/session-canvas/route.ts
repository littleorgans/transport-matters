export interface CanvasLaunchContext {
  owner: "local";
  workspaceHash: string | null;
  spaceId: string | null;
  worktreeId: string | null;
  canvasId: string | null;
  harness: string | null;
  runId: string | null;
}

export function parseCanvasLaunchContext(search: string | URLSearchParams): CanvasLaunchContext {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  return {
    owner: "local",
    workspaceHash: valueOrNull(params.get("workspace_hash")),
    spaceId: valueOrNull(params.get("space_id")),
    worktreeId: valueOrNull(params.get("worktree_id")),
    canvasId: valueOrNull(params.get("canvas_id")),
    harness: valueOrNull(params.get("harness")),
    runId: valueOrNull(params.get("run_id")),
  };
}

/**
 * The localStorage cache key id for this launch. A Space's default Canvas is
 * `space:<spaceId>` (one default Canvas per Space); an explicit `canvas_id`
 * overrides; a worktree-less / pre-Spaces launch keeps the legacy `workspaceHash`
 * (or `direct-local`) so existing single-canvas behaviour is preserved.
 */
export function defaultCanvasId(launch: CanvasLaunchContext): string {
  if (launch.canvasId) return launch.canvasId;
  if (launch.spaceId) return `space:${launch.spaceId}`;
  return launch.workspaceHash ?? "direct-local";
}

/**
 * In-place URL for a worktree switch: set `space_id` + `worktree_id` EXACTLY once on
 * the current search, and drop any pinned `canvas_id` so the canvas re-keys to the new
 * Space's default rather than staying pinned to the old canvas. Hand the result to
 * `history.replaceState` — NEVER to `navigateToRoute`, which re-appends
 * `window.location.search` and would yield a double-"?" URL that corrupts `worktree_id`
 * on reload.
 */
export function worktreeSwitchUrl(
  pathname: string,
  search: string,
  spaceId: string,
  worktreeId: string,
): string {
  const params = new URLSearchParams(search);
  params.set("space_id", spaceId);
  params.set("worktree_id", worktreeId);
  params.delete("canvas_id");
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function isStressCanvas(search: string | URLSearchParams): boolean {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  return params.get("stress") === "1";
}

function valueOrNull(value: string | null): string | null {
  if (value === null) return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
