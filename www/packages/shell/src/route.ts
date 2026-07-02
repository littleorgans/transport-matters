export type RootRoute = "canvas" | "canvas-lab" | "inspector";

export function selectRootRoute(pathname: string): RootRoute {
  if (pathname === "/canvas") return "canvas";
  if (pathname === "/canvas-lab") return "canvas-lab";
  return "inspector";
}
