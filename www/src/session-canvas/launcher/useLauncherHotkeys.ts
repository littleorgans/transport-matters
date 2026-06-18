import { useLauncherKeybindings } from "../../keybindings/engine";
import type { LauncherScope } from "./commandModel";

export interface LauncherHotkeyHandlers {
  /** ⌘K / ⌃K: toggle the command center open at the root (domains) scope. */
  toggleRoot: () => void;
  /** Open the palette straight into a scope (the accelerator jump). */
  openScope: (scope: LauncherScope) => void;
  /** Read the live open state without re-binding the listener. */
  isOpen: () => boolean;
}

/**
 * Registers launcher handlers with the desktop keybinding engine. The engine
 * owns the single bubble phase window listener; the command center keeps its
 * capture phase Escape listener.
 */
export function useLauncherHotkeys({
  toggleRoot,
  openScope,
  isOpen,
}: LauncherHotkeyHandlers): void {
  useLauncherKeybindings({ toggleRoot, openScope, isOpen });
}
