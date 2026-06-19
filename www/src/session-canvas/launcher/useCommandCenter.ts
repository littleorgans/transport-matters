import {
  type KeyboardEvent,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CanvasGestureModifier } from "../../keybindings/gestureModifier";
import {
  type CommandRow,
  createRootNavFrame,
  domainRowValue,
  interactionFor,
  type LauncherCommand,
  type LauncherEffect,
  type LauncherScope,
  type Lifecycle,
  type NavFrame,
  popFrame,
  pushFrame,
  type RowAction,
  topFrame,
  updateTopFrame,
} from "./commandModel";
import { useLauncherHotkeys } from "./useLauncherHotkeys";
import { useLauncherRows } from "./useLauncherRows";
import { useRuntimeTemplates } from "./useRuntimeTemplates";

export interface UseCommandCenterArgs {
  /** Leaf command dispatcher; the canvas binds these to its store/handlers. */
  onCommand: (command: LauncherCommand) => void;
  /** Current theme name, shown on the Cycle-theme entry's subtitle. */
  themeName: string;
  /** Current persisted canvas gesture modifier, shown in Settings. */
  canvasGestureModifier: CanvasGestureModifier;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled launcher lifecycle: ${String(value)}`);
}

interface LauncherActionInterpreterArgs {
  onCommand: (command: LauncherCommand) => void;
  retry: () => void;
  close: () => void;
  descend: (scope: LauncherScope, originValue: string) => void;
}

interface NavFrameController {
  scope: LauncherScope;
  query: string;
  highlighted: string | undefined;
  canBack: boolean;
  resetStack: () => void;
  setQuery: (query: string) => void;
  setHighlighted: (next: SetStateAction<string | undefined>) => void;
  descend: (scope: LauncherScope, originValue: string) => void;
  back: () => void;
  openScopeStack: (scope: LauncherScope) => void;
}

function useLauncherActionInterpreter({
  onCommand,
  retry,
  close,
  descend,
}: LauncherActionInterpreterArgs) {
  const effectSink = useMemo<Record<LauncherEffect, () => void>>(
    () => ({ "retry-agents": retry }),
    [retry],
  );

  const fire = useCallback(
    (action: RowAction) => {
      switch (action.kind) {
        case "command":
          onCommand(action.command);
          return;
        case "effect":
          effectSink[action.effect]();
          return;
        case "enter":
          return;
      }
    },
    [onCommand, effectSink],
  );

  return useCallback(
    (row: CommandRow, lifecycle: Lifecycle) => {
      const action = row.action;
      if (!action) return;
      switch (lifecycle) {
        case "descend":
          if (action.kind === "enter") {
            descend(action.scope, row.value);
          }
          return;
        case "run-close":
          fire(action);
          close();
          return;
        case "run-stay":
          fire(action);
          return;
        case "commit-close":
          close();
          return;
        case "none":
          return;
        default:
          assertNever(lifecycle);
      }
    },
    [close, descend, fire],
  );
}

function useNavFrameStack(): NavFrameController {
  const [stack, setStack] = useState<NavFrame[]>(() => [createRootNavFrame()]);
  const frame = topFrame(stack);

  const resetStack = useCallback(() => setStack([createRootNavFrame()]), []);

  const setQuery = useCallback(
    (nextQuery: string) =>
      setStack((current) => {
        const currentFrame = topFrame(current);
        return currentFrame.query === nextQuery
          ? current
          : updateTopFrame(current, { query: nextQuery });
      }),
    [],
  );

  const setHighlighted = useCallback((next: SetStateAction<string | undefined>) => {
    setStack((current) => {
      const currentValue = topFrame(current).highlightedValue;
      const nextValue = typeof next === "function" ? next(currentValue) : next;
      return currentValue === nextValue
        ? current
        : updateTopFrame(current, { highlightedValue: nextValue });
    });
  }, []);

  const descend = useCallback(
    (target: LauncherScope, originValue: string) =>
      setStack((current) => pushFrame(current, target, originValue)),
    [],
  );

  const back = useCallback(() => setStack(popFrame), []);
  const openScopeStack = useCallback(
    (target: LauncherScope) =>
      setStack(pushFrame([createRootNavFrame()], target, domainRowValue(target))),
    [],
  );

  return {
    scope: frame.scope,
    query: frame.query,
    highlighted: frame.highlightedValue,
    canBack: stack.length > 1,
    resetStack,
    setQuery,
    setHighlighted,
    descend,
    back,
    openScopeStack,
  };
}

/**
 * Palette state + grammar half of the ⌘K command center: open/scope/query
 * state, focus save-restore, the renderer-level hotkeys, the lazy specialist
 * fetch, and the keyboard grammar. Row derivation lives in {@link useLauncherRows}.
 * Mirrors the useRuntimeTemplates/useLauncherHotkeys split so {@link CommandCenter}
 * stays a thin Ark composition. Behaviour is the component's former inline logic,
 * lifted verbatim.
 */
export function useCommandCenter({
  onCommand,
  themeName,
  canvasGestureModifier,
}: UseCommandCenterArgs) {
  const [open, setOpen] = useState(false);
  const {
    scope,
    query,
    highlighted,
    canBack,
    resetStack,
    setQuery,
    setHighlighted,
    descend,
    back,
    openScopeStack,
  } = useNavFrameStack();
  // Sticky: the specialist fleet fetches on the FIRST open and stays cached, so
  // a never-opened palette never hits the endpoint (and never blocks a spawn).
  const [hasOpened, setHasOpened] = useState(false);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const { templates, status, retry } = useRuntimeTemplates(hasOpened);

  const close = useCallback(() => {
    setOpen(false);
    resetStack();
    restoreFocusRef.current?.focus?.();
    restoreFocusRef.current = null;
  }, [resetStack]);

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
    resetStack();
  }, [rememberFocus, resetStack]);

  const openScope = useCallback(
    (target: LauncherScope) => {
      rememberFocus();
      setHasOpened(true);
      openScopeStack(target);
      setOpen(true);
    },
    [rememberFocus, openScopeStack],
  );

  const isOpenRef = useRef(open);
  isOpenRef.current = open;
  useLauncherHotkeys({ toggleRoot, openScope, isOpen: () => isOpenRef.current });

  const { collection, grouped, rowByValue, fleetStatus } = useLauncherRows({
    scope,
    query,
    templates,
    status,
    themeName,
    canvasGestureModifier,
    setHighlighted,
  });

  const applyGesture = useLauncherActionInterpreter({
    onCommand,
    retry,
    close,
    descend,
  });

  const selectValue = useCallback(
    (value: string | undefined) => {
      const row = value ? rowByValue.get(value) : undefined;
      if (row?.action) applyGesture(row, interactionFor(row.action).enter);
    },
    [rowByValue, applyGesture],
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
        if (row?.action) {
          const lifecycle = interactionFor(row.action).advance;
          if (lifecycle !== "none") {
            event.preventDefault();
            applyGesture(row, lifecycle);
          }
        }
        return;
      }
      const popsToRoot =
        event.key === "ArrowLeft" ? caret === 0 : event.key === "Backspace" && query.length === 0;
      if (popsToRoot && canBack) {
        event.preventDefault();
        back();
      }
    },
    [query.length, highlighted, rowByValue, applyGesture, canBack, back],
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
