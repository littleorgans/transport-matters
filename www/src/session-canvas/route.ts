export type RootRoute = "canvas" | "canvas-lab" | "legacy";

export interface CanvasLaunchContext {
  owner: "local";
  workspaceHash: string | null;
  cli: string | null;
  runId: string | null;
}

export function selectRootRoute(pathname: string): RootRoute {
  if (pathname === "/canvas") return "canvas";
  if (pathname === "/canvas-lab") return "canvas-lab";
  return "legacy";
}

export function parseCanvasLaunchContext(search: string | URLSearchParams): CanvasLaunchContext {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  return {
    owner: "local",
    workspaceHash: valueOrNull(params.get("workspace_hash")),
    cli: valueOrNull(params.get("cli")),
    runId: valueOrNull(params.get("run_id")),
  };
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
