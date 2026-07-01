export interface WorktreeDefaultState {
  defaultWorktreeId: string | null;
  spaceId: string | null;
}

export const ROOTED_WORKTREE_REQUIRED_MESSAGE =
  "Cannot spawn a captured run without a rooted worktree";

export function requireWorktreeId(worktreeId: string | null): string {
  if (worktreeId === null) throw new Error(ROOTED_WORKTREE_REQUIRED_MESSAGE);
  return worktreeId;
}

export function defaultWorktreePatch(
  state: WorktreeDefaultState,
  spaceId: string | null,
  worktreeId: string,
): Partial<WorktreeDefaultState> {
  return {
    spaceId: spaceId ?? state.spaceId,
    defaultWorktreeId: worktreeId,
  };
}

export function adoptDefaultWorktreePatch(
  state: WorktreeDefaultState,
  spaceId: string | null,
  worktreeId: string,
): Partial<WorktreeDefaultState> {
  return state.defaultWorktreeId === null ? defaultWorktreePatch(state, spaceId, worktreeId) : {};
}
