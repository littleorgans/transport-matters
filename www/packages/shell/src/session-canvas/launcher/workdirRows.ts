// Workdir-domain row builders: the Space rows and the Worktree sub-scope rows,
// split out of commandModel to keep that file under the size limit. Pure functions
// of their inputs; depends on commandModel only for row types (erased at runtime,
// so the runtime dependency stays one-way: commandModel → workdirRows).

import type { SpaceSummary, WorktreeSummary } from "@tm/core";
import { locatorTail } from "../model/paneRecords";
import type { CommandRow } from "./commandModel";

const GROUP_WORKDIR = "Workdir";

/**
 * The dual-gesture binding shared by every directly-selectable worktree (the
 * single-worktree Space row and the Worktree sub-scope rows): ↵ runs
 * `select-worktree` (set the default spawn target), → drills into the Agents scope
 * pinned to this worktree so spawns coexist without toggling the global default.
 */
function worktreeRowActions(
  spaceId: string,
  worktreeId: string,
): Pick<CommandRow, "action" | "advance"> {
  return {
    action: { kind: "command", command: { kind: "select-worktree", spaceId, worktreeId } },
    advance: { kind: "enter", scope: "agents", param: worktreeId },
  };
}

/** Subtitle for a worktree row: its root path. */
function worktreeSubtitle(worktree: WorktreeSummary): string {
  return worktree.path;
}

/** Title for a worktree row: the branch, else "main worktree", else the path tail. */
function worktreeTitle(worktree: WorktreeSummary): string {
  if (worktree.branch) return worktree.branch;
  return worktree.isPrimary ? "main worktree" : locatorTail(worktree.path);
}

/**
 * Workdir scope: one row per detected Space (R7). Rows are titled by the project
 * label (never the bare word "Space"), so they never read like the Settings
 * "Canvas gesture modifier: Space" row. A single available worktree selects
 * directly; a multi-worktree Space descends into the worktree sub-scope; a single
 * MISSING worktree is inert (no select, no spawn drill-in).
 */
export function buildSpaceRows(
  spaces: SpaceSummary[],
  activeWorktreeId: string | null,
): CommandRow[] {
  if (spaces.length === 0) {
    return [
      {
        value: "status:workdir-empty",
        title: "No spaces detected yet",
        subtitle: "Open a project directory to capture a Space",
        group: GROUP_WORKDIR,
        disabled: true,
      },
    ];
  }
  return spaces.map((space): CommandRow => {
    const single = space.worktrees.length === 1 ? space.worktrees[0] : undefined;
    const missing = single?.missing ?? false;
    const rooted = single?.worktreeId === activeWorktreeId;
    const row: CommandRow = {
      value: `space:${space.spaceId}`,
      title: space.label,
      subtitle: single ? worktreeSubtitle(single) : `${space.worktrees.length} worktrees`,
      group: GROUP_WORKDIR,
      trailing: missing ? "Missing" : rooted ? "Current" : space.kind === "repo" ? "repo" : "dir",
    };
    // Multi-worktree Space → descend into the sub-scope. A single AVAILABLE worktree
    // → ↵ selects it with a → drill-in. A single MISSING worktree stays inert so the
    // launcher never offers a spawn the backend would reject (unavailable worktree_id).
    if (!single) {
      return { ...row, action: { kind: "enter", scope: "worktree", param: space.spaceId } };
    }
    if (missing) return { ...row, disabled: true };
    return { ...row, ...worktreeRowActions(space.spaceId, single.worktreeId) };
  });
}

/** Worktree sub-scope: one row per worktree of the Space named by `spaceId` (the nav param). */
export function buildWorktreeRows(
  spaces: SpaceSummary[],
  spaceId: string | undefined,
  activeWorktreeId: string | null,
): CommandRow[] {
  const space = spaces.find((candidate) => candidate.spaceId === spaceId);
  if (!space) {
    return [
      {
        value: "status:worktree-missing",
        title: "Space no longer available",
        group: GROUP_WORKDIR,
        disabled: true,
      },
    ];
  }
  return space.worktrees.map(
    (worktree): CommandRow => ({
      value: `worktree:${worktree.worktreeId}`,
      title: worktreeTitle(worktree),
      subtitle: worktreeSubtitle(worktree),
      group: GROUP_WORKDIR,
      trailing:
        worktree.worktreeId === activeWorktreeId
          ? "Current"
          : worktree.missing
            ? "Missing"
            : undefined,
      disabled: worktree.missing,
      // Missing worktrees are inert; live ones get ↵=set-default + →=drill-into-spawn.
      ...(worktree.missing ? {} : worktreeRowActions(space.spaceId, worktree.worktreeId)),
    }),
  );
}
