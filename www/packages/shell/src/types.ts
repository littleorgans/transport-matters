export type * from "./types/breakpoints";
export type * from "./types/capabilities";
export type * from "./types/codex";
export type * from "./types/exchanges";
export type * from "./types/ir";
export type * from "./types/overrides";
export type * from "./types/runtimeTemplates";
export type * from "./types/transport";

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
