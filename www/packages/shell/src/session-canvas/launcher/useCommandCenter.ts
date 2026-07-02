import { type SetStateAction, useCallback, useMemo, useRef, useState } from "react";
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
import { useLauncherInputKeys } from "./useLauncherInputKeys";
import { useLauncherRows } from "./useLauncherRows";
import { useRuntimeTemplates } from "./useRuntimeTemplates";
import { useSessionHistory } from "./useSessionHistory";
import { useSpaces } from "./useSpaces";

export interface UseCommandCenterArgs {
  /** Leaf command dispatcher; the canvas binds these to its store/handlers. */
  onCommand: (command: LauncherCommand) => void;
  /** Current theme name, shown on the Cycle-theme entry's subtitle. */
  themeName: string;
  /** Current persisted canvas gesture modifier, shown in Settings. */
  canvasGestureModifier: CanvasGestureModifier;
  /** Current persisted bypass-permissions flag, shown on the Settings toggle. */
  bypassPermissions: boolean;
  /** The canvas's rooted worktree, marked "Current" in the Space/Worktree rows. */
  activeWorktreeId: string | null;
  /** The canvas workspace the Sessions scope browses transcript history for. */
  workspaceHash: string | null;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled launcher lifecycle: ${String(value)}`);
}

interface LauncherActionInterpreterArgs {
  onCommand: (command: LauncherCommand) => void;
  retry: () => void;
  retrySessions: () => void;
  close: () => void;
  descend: (scope: LauncherScope, originValue: string, param?: string) => void;
}

interface NavFrameController {
  scope: LauncherScope;
  query: string;
  param: string | undefined;
  highlighted: string | undefined;
  canBack: boolean;
  resetStack: () => void;
  setQuery: (query: string) => void;
  setHighlighted: (next: SetStateAction<string | undefined>) => void;
  descend: (scope: LauncherScope, originValue: string, param?: string) => void;
  back: () => void;
  openScopeStack: (scope: LauncherScope) => void;
}

function useLauncherActionInterpreter({
  onCommand,
  retry,
  retrySessions,
  close,
  descend,
}: LauncherActionInterpreterArgs) {
  const effectSink = useMemo<Record<LauncherEffect, () => void>>(
    () => ({ "retry-agents": retry, "retry-sessions": retrySessions }),
    [retry, retrySessions],
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
    (row: CommandRow, action: RowAction, lifecycle: Lifecycle) => {
      switch (lifecycle) {
        case "descend":
          if (action.kind === "enter") {
            descend(action.scope, row.value, action.param);
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
    (target: LauncherScope, originValue: string, param?: string) =>
      setStack((current) => pushFrame(current, target, originValue, param)),
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
    param: frame.param,
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
  bypassPermissions,
  activeWorktreeId,
  workspaceHash,
}: UseCommandCenterArgs) {
  const [open, setOpen] = useState(false);
  const {
    scope,
    query,
    param,
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
  // Lazy like the specialist fleet: only fetch /v1/spaces once the palette has been
  // opened, so a never-opened command center never hits the endpoint (matches the
  // useSpaces docstring instead of eager-fetching on every canvas mount).
  const spaces = useSpaces(hasOpened);
  // Same laziness for the Sessions scope: browse transcript history for the current
  // workspace, fetched only once the palette has been opened.
  const {
    sessions,
    status: sessionsStatus,
    retry: retrySessions,
  } = useSessionHistory(workspaceHash, hasOpened);

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
    param,
    templates,
    status,
    themeName,
    canvasGestureModifier,
    bypassPermissions,
    spaces,
    activeWorktreeId,
    sessions,
    sessionsStatus,
    setHighlighted,
  });

  const applyGesture = useLauncherActionInterpreter({
    onCommand,
    retry,
    retrySessions,
    close,
    descend,
  });

  const selectValue = useCallback(
    (value: string | undefined) => {
      const row = value ? rowByValue.get(value) : undefined;
      // ↵/click always drives the PRIMARY action's enter lifecycle; → (advance) is
      // handled separately in useLauncherInputKeys via advanceGesture.
      if (row?.action) applyGesture(row, row.action, interactionFor(row.action).enter);
    },
    [rowByValue, applyGesture],
  );

  const onInputKeyDown = useLauncherInputKeys({
    open,
    close,
    query,
    highlighted,
    rowByValue,
    applyGesture,
    canBack,
    back,
  });

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
