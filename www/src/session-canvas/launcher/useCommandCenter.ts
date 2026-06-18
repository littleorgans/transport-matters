import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import type { LauncherCommand, LauncherScope, RowAction } from "./commandModel";
import { useLauncherHotkeys } from "./useLauncherHotkeys";
import { useLauncherRows } from "./useLauncherRows";
import { useRuntimeTemplates } from "./useRuntimeTemplates";

export interface UseCommandCenterArgs {
  /** Leaf command dispatcher; the canvas binds these to its store/handlers. */
  onCommand: (command: LauncherCommand) => void;
  /** Current theme name, shown on the Cycle-theme entry's subtitle. */
  themeName: string;
}

/**
 * Palette state + grammar half of the ⌘K command center: open/scope/query
 * state, focus save-restore, the renderer-level hotkeys, the lazy specialist
 * fetch, and the keyboard grammar. Row derivation lives in {@link useLauncherRows}.
 * Mirrors the useRuntimeTemplates/useLauncherHotkeys split so {@link CommandCenter}
 * stays a thin Ark composition. Behaviour is the component's former inline logic,
 * lifted verbatim.
 */
export function useCommandCenter({ onCommand, themeName }: UseCommandCenterArgs) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<LauncherScope>("root");
  const [query, setQuery] = useState("");
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

  const openScope = useCallback(
    (target: LauncherScope) => {
      rememberFocus();
      setHasOpened(true);
      setScope(target);
      setQuery("");
      setOpen(true);
    },
    [rememberFocus],
  );

  const isOpenRef = useRef(open);
  isOpenRef.current = open;
  useLauncherHotkeys({ toggleRoot, openScope, isOpen: () => isOpenRef.current });

  const { collection, grouped, rowByValue, highlighted, setHighlighted, fleetStatus } =
    useLauncherRows({ scope, query, templates, status, themeName });

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

  // Own Escape so it ALWAYS closes the whole palette, from any state (listbox
  // open, a scope entered, query empty or not); ←/⌫ remain the scope-pop grammar.
  // Ark's combobox dismisses Escape via a DOCUMENT-level capture listener that
  // only closes its own listbox / clears the input. A WINDOW capture listener
  // runs earlier in the capture path (window precedes document), so we close the
  // palette and stopPropagation before Ark can consume the key. Active only while
  // open.
  useEffect(() => {
    if (!open) return;
    const onEscapeCapture = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    window.addEventListener("keydown", onEscapeCapture, true);
    return () => window.removeEventListener("keydown", onEscapeCapture, true);
  }, [open, close]);

  const onInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
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
    [query.length, highlighted, rowByValue, runAction, scope],
  );

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
