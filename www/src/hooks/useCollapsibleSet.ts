import { useState } from "react";

/**
 * Expand/collapse state for a set of indexed rows that share a master
 * toggle. Tracks which rows are *collapsed* (so the common "everything
 * open" state is the empty set).
 *
 * `startCollapsed` picks the initial configuration — consumers typically
 * read it from a preference in the initializer so that mid-session flips
 * don't retroactively fold or unfold already-mounted rows.
 */
export function useCollapsibleSet(count: number, startCollapsed: boolean) {
  const [collapsed, setCollapsed] = useState<Set<number>>(() =>
    startCollapsed ? new Set(Array.from({ length: count }, (_, i) => i)) : new Set(),
  );
  const allExpanded = collapsed.size === 0;

  const toggleAll = () => {
    setCollapsed(allExpanded ? new Set(Array.from({ length: count }, (_, i) => i)) : new Set());
  };

  const toggleOne = (idx: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const isExpanded = (idx: number) => !collapsed.has(idx);

  return { collapsed, allExpanded, toggleAll, toggleOne, isExpanded };
}
