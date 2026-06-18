import { createListCollection } from "@ark-ui/react/combobox";
import { useEffect, useMemo, useState } from "react";
import type { RuntimeTemplateSummary } from "../../types";
import {
  type AgentsStatus,
  buildScopeRows,
  filterRows,
  firstSelectableValue,
  groupRows,
  type LauncherScope,
  type ScopeRowInputs,
} from "./commandModel";

export interface LauncherRowsArgs {
  scope: LauncherScope;
  query: string;
  templates: RuntimeTemplateSummary[];
  status: AgentsStatus;
  themeName: string;
}

/**
 * Row-building half of the command center: derives the visible rows for the
 * current scope/query, the Ark collection that backs the combobox, and the
 * grouped/lookup views; keeps a valid row highlighted as the set narrows; and
 * maps the async fleet status into a polite announcement. Split out of
 * {@link useCommandCenter} so the main hook owns only palette state + grammar.
 */
export function useLauncherRows({ scope, query, templates, status, themeName }: LauncherRowsArgs) {
  const [highlighted, setHighlighted] = useState<string | undefined>(undefined);

  const inputs = useMemo<ScopeRowInputs>(
    () => ({ templates, agentsStatus: status, themeName }),
    [templates, status, themeName],
  );
  const visibleRows = useMemo(
    () => filterRows(buildScopeRows(scope, inputs, query), query),
    [scope, inputs, query],
  );
  const rowByValue = useMemo(
    () => new Map(visibleRows.map((row) => [row.value, row])),
    [visibleRows],
  );
  const grouped = useMemo(() => groupRows(visibleRows), [visibleRows]);
  const collection = useMemo(
    () =>
      createListCollection({
        items: visibleRows,
        itemToValue: (row) => row.value,
        itemToString: (row) => row.title,
        isItemDisabled: (row) => Boolean(row.disabled),
      }),
    [visibleRows],
  );

  // Keep a valid, selectable row highlighted as the scope/query narrows so ↵ and
  // → always act on something sensible.
  useEffect(() => {
    setHighlighted((current) =>
      current && visibleRows.some((row) => row.value === current && !row.disabled)
        ? current
        : firstSelectableValue(visibleRows),
    );
  }, [visibleRows]);

  // Visually-hidden polite announcement for the async specialist fetch, so the
  // loading → error transition is discoverable without arrowing into a disabled
  // option. Only meaningful where agent rows render (root/agents).
  const showsAgents = scope === "root" || scope === "agents";
  const fleetStatus =
    showsAgents && status === "loading"
      ? "Loading specialist agents"
      : showsAgents && status === "error"
        ? "Could not load specialist agents. Native agents are still available."
        : "";

  return { collection, grouped, rowByValue, highlighted, setHighlighted, fleetStatus };
}
