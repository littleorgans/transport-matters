export interface LauncherKeybindingTarget {
  toggleRoot: () => void;
  openScope: (scope: "agents" | "settings") => void;
  isOpen: () => boolean;
}

export interface DockKeybindingTarget {
  close: () => void;
  isOpen: () => boolean;
}

export interface FullscreenKeybindingTarget {
  close: () => void;
  isOpen: () => boolean;
}

export interface CommandContext {
  event: KeyboardEvent;
  editableTarget: boolean;
  launcher: LauncherKeybindingTarget | null;
  dock: DockKeybindingTarget | null;
  fullscreen: FullscreenKeybindingTarget | null;
}

export type ContextPredicate = (ctx: CommandContext) => boolean;

export type Command = {
  id: string;
  title: string;
  category: string;
  defaultKeys: string[];
  when?: ContextPredicate;
  configurable?: boolean;
  priority?: number;
  run: (ctx: CommandContext) => void;
};
