import { createListCollection } from "@ark-ui/react/combobox";
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  buildScopeRows,
  filterRows,
  firstSelectableValue,
  groupRows,
  type LauncherCommand,
  type LauncherScope,
  type RowAction,
  type ScopeRowInputs,
} from "./commandModel";
import { useLauncherHotkeys } from "./useLauncherHotkeys";
import { useRuntimeTemplates } from "./useRuntimeTemplates";

export interface UseCommandCenterArgs {
  /** Leaf command dispatcher; the canvas binds these to its store/handlers. */
  onCommand: (command: LauncherCommand) => void;
  /** Current theme name, shown on the Cycle-theme entry's subtitle. */
  themeName: string;
}

/**
 * All non-render concerns of the ⌘K command center: open/scope/query/highlight
 * state, focus save-restore, the renderer-level hotkeys, the lazy specialist
 * fetch, the derived row collection, and the keyboard grammar. Mirrors the
 * useRuntimeTemplates/useLauncherHotkeys split so {@link CommandCenter} stays a
 * thin Ark composition. Everything here is behaviour the component used to own
 * inline; it is lifted verbatim, not changed.
 */
export function useCommandCenter({ onCommand, themeName }: UseCommandCenterArgs) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<LauncherScope>("root");
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState<string | undefined>(undefined);
  // Sticky: the specialist fleet fetches on the FIRST open and stays cached, so
  // a never-opened palette never hits the endpoint (and never blocks a spawn).
  const [hasOpened, setHasOpened] = useState(false);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const { templates, status, retry } = useRuntimeTemplates(hasOpened);

  const close = useCallback(() => {
    setOpen(false);
    setScope("root");
    setQuery("");
    restoreFocusRef.current?.focus?.();
    restoreFocusRef.current = null;
  }, []);

  const rememberFocus = useCallback(() => {
    const active = document.activeElement;
    restoreFocusRef.current = active instanceof HTMLElement ? active : null;
  }, []);

  const toggleRoot = useCallback(() => {
    setOpen((wasOpen) => {
      if (wasOpen) {
        restoreFocusRef.current?.focus?.();
        restoreFocusRef.current = null;
        return false;
      }
      rememberFocus();
      return true;
    });
    setHasOpened(true);
    setScope("root");
    setQuery("");
  }, [rememberFocus]);

  const openAgents = useCallback(() => {
    rememberFocus();
    setHasOpened(true);
    setScope("agents");
    setQuery("");
    setOpen(true);
  }, [rememberFocus]);

  const isOpenRef = useRef(open);
  isOpenRef.current = open;
  useLauncherHotkeys({ toggleRoot, openAgents, isOpen: () => isOpenRef.current });

  const inputs = useMemo<ScopeRowInputs>(
    () => ({ templates, agentsStatus: status, themeName }),
    [templates, status, themeName],
  );
  const visibleRows = useMemo(
    () => filterRows(buildScopeRows(scope, inputs), query),
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

  const runAction = useCallback(
    (action: RowAction) => {
      if (action.kind === "enter") {
        setScope(action.scope);
        setQuery("");
        return;
      }
      if (action.command.kind === "retry-agents") {
        retry();
        return;
      }
      onCommand(action.command);
      close();
    },
    [onCommand, retry, close],
  );

  const selectValue = useCallback(
    (value: string | undefined) => {
      const row = value ? rowByValue.get(value) : undefined;
      if (row?.action) runAction(row.action);
    },
    [rowByValue, runAction],
  );

  const onInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      const caret = event.currentTarget.selectionStart ?? 0;
      if (event.key === "ArrowRight" && caret >= query.length) {
        const row = highlighted ? rowByValue.get(highlighted) : undefined;
        if (row?.action?.kind === "enter") {
          event.preventDefault();
          runAction(row.action);
        }
        return;
      }
      const popsToRoot =
        event.key === "ArrowLeft" ? caret === 0 : event.key === "Backspace" && query.length === 0;
      if (popsToRoot && scope !== "root") {
        event.preventDefault();
        setScope("root");
      }
    },
    [close, query.length, highlighted, rowByValue, runAction, scope],
  );

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

  return {
    open,
    scope,
    query,
    highlighted,
    collection,
    grouped,
    fleetStatus,
    close,
    setQuery,
    setHighlighted,
    selectValue,
    onInputKeyDown,
  };
}
