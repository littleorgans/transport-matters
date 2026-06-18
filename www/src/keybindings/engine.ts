import {
  createContext,
  createElement,
  type MutableRefObject,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { type KeybindingsMap, tinykeys } from "tinykeys";
import { isEditableTarget } from "../lib/domFocus";
import { getKeybindingPlatform, type KeybindingPlatform, precompileModTokens } from "./platform";
import {
  COMMANDS,
  type Command,
  type CommandContext,
  type DockKeybindingTarget,
  type FullscreenKeybindingTarget,
  type LauncherKeybindingTarget,
} from "./registry";

interface KeybindingEngineApi {
  registerDock(target: DockKeybindingTarget): () => void;
  registerFullscreen(target: FullscreenKeybindingTarget): () => void;
  registerLauncher(target: LauncherKeybindingTarget): () => void;
}

interface KeybindingEngineProviderProps {
  children?: ReactNode;
  commands?: readonly Command[];
  platform?: KeybindingPlatform;
}

interface CreateKeybindingMapOptions {
  commands: readonly Command[];
  getContext: (event: KeyboardEvent) => CommandContext;
  platform: KeybindingPlatform;
}

const KeybindingEngineContext = createContext<KeybindingEngineApi | null>(null);

export function KeybindingEngineProvider({
  children,
  commands = COMMANDS,
  platform,
}: KeybindingEngineProviderProps) {
  const launcherRef = useRef<LauncherKeybindingTarget | null>(null);
  const dockRef = useRef<DockKeybindingTarget | null>(null);
  const fullscreenRef = useRef<FullscreenKeybindingTarget | null>(null);
  const resolvedPlatform = useMemo(() => platform ?? getKeybindingPlatform(), [platform]);
  const api = useMemo<KeybindingEngineApi>(
    () => ({
      registerDock: (target) => registerSlot(dockRef, target),
      registerFullscreen: (target) => registerSlot(fullscreenRef, target),
      registerLauncher: (target) => registerSlot(launcherRef, target),
    }),
    [],
  );
  const getContext = useMemo(
    () =>
      (event: KeyboardEvent): CommandContext => ({
        event,
        editableTarget: isEditableTarget(event.target),
        launcher: launcherRef.current,
        dock: dockRef.current,
        fullscreen: fullscreenRef.current,
      }),
    [],
  );
  const keybindings = useMemo(
    () => createKeybindingMap({ commands, platform: resolvedPlatform, getContext }),
    [commands, resolvedPlatform, getContext],
  );

  useEffect(() => {
    return tinykeys(window, keybindings, {
      capture: false,
      event: "keydown",
      // Command gates own editable yield, because Settings intentionally works
      // from editable targets while Agents intentionally yields to Select All.
      // Capture phase owners such as the command center mark handled Escape
      // with preventDefault, so the bubble registry stands down.
      ignore: (event) => event.defaultPrevented,
    });
  }, [keybindings]);

  return createElement(KeybindingEngineContext.Provider, { value: api }, children);
}

export function createKeybindingMap({
  commands,
  platform,
  getContext,
}: CreateKeybindingMapOptions): KeybindingsMap {
  const groups = groupCommandsByBinding(commands, platform);
  const keybindings: KeybindingsMap = {};
  for (const [binding, bindingCommands] of groups) {
    keybindings[binding] = (event) => {
      dispatchKeybinding(bindingCommands, getContext(event));
    };
  }
  return keybindings;
}

export function dispatchKeybinding(commands: readonly Command[], ctx: CommandContext): void {
  const command = selectCommand(commands, ctx);
  command?.run(ctx);
}

export function selectCommand(commands: readonly Command[], ctx: CommandContext): Command | null {
  let selected: Command | null = null;
  for (const command of commands) {
    if (command.when && !command.when(ctx)) continue;
    if (selected === null || priorityOf(command) > priorityOf(selected)) {
      selected = command;
    }
  }
  return selected;
}

export function precompileKeybinding(binding: string, platform: KeybindingPlatform): string {
  return binding
    .trim()
    .split(" ")
    .filter((press) => press.length > 0)
    .map((press) =>
      press
        .split("+")
        .map((token) => precompileKeybindingToken(token, platform))
        .join("+"),
    )
    .join(" ");
}

export function useLauncherKeybindings(target: LauncherKeybindingTarget): void {
  const api = useContext(KeybindingEngineContext);
  const targetRef = useLatestTarget(target);
  useEffect(() => {
    if (!api) return;
    return api.registerLauncher({
      toggleRoot: () => targetRef.current.toggleRoot(),
      openScope: (scope) => targetRef.current.openScope(scope),
      isOpen: () => targetRef.current.isOpen(),
    });
  }, [api, targetRef]);
}

export function useDockKeybindings(target: DockKeybindingTarget): void {
  const api = useContext(KeybindingEngineContext);
  const targetRef = useLatestTarget(target);
  const open = target.isOpen();
  useEffect(() => {
    if (!api) return;
    return api.registerDock({
      close: () => targetRef.current.close(),
      isOpen: () => targetRef.current.isOpen(),
    });
  }, [api, targetRef]);
  useEscapeFallback(!api && open, () => targetRef.current.close());
}

export function useFullscreenKeybindings(target: FullscreenKeybindingTarget): void {
  const api = useContext(KeybindingEngineContext);
  const targetRef = useLatestTarget(target);
  const open = target.isOpen();
  useEffect(() => {
    if (!api) return;
    return api.registerFullscreen({
      close: () => targetRef.current.close(),
      isOpen: () => targetRef.current.isOpen(),
    });
  }, [api, targetRef]);
  useEscapeFallback(!api && open, () => targetRef.current.close());
}

function groupCommandsByBinding(
  commands: readonly Command[],
  platform: KeybindingPlatform,
): Map<string, Command[]> {
  const groups = new Map<string, Command[]>();
  for (const command of commands) {
    for (const binding of command.defaultKeys) {
      const compiled = precompileKeybinding(binding, platform);
      const group = groups.get(compiled);
      if (group) group.push(command);
      else groups.set(compiled, [command]);
    }
  }
  return groups;
}

function registerSlot<T>(slot: MutableRefObject<T | null>, target: T): () => void {
  slot.current = target;
  return () => {
    if (slot.current === target) slot.current = null;
  };
}

function useLatestTarget<T>(target: T): MutableRefObject<T> {
  const targetRef = useRef(target);
  targetRef.current = target;
  return targetRef;
}

function useEscapeFallback(enabled: boolean, close: () => void): void {
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}

function precompileKeybindingToken(token: string, platform: KeybindingPlatform): string {
  const trimmed = token.trim();
  const optional = trimmed.match(/^\[(.*)\]$/);
  if (optional) return `[${precompileKeybindingToken(optional[1] ?? "", platform)}]`;
  return precompileModTokens([trimmed], platform)[0] ?? trimmed;
}

function priorityOf(command: Command): number {
  return command.priority ?? 0;
}
