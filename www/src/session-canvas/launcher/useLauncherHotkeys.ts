import { useEffect } from "react";
import { isEditableTarget } from "../../lib/domFocus";

export interface LauncherHotkeyHandlers {
  /** ⌘K / ⌃K: toggle the command center open at the root scope. */
  toggleRoot: () => void;
  /** ⌘A / ⌃A: jump straight into the Agents scope (the 99% launch path). */
  openAgents: () => void;
  /** Read the live open state without re-binding the listener. */
  isOpen: () => boolean;
}

/**
 * Renderer-level keydown dispatcher for the command center (NOT Electron
 * globalShortcut — the palette is renderer chrome). ⌘K toggles root; ⌘A opens
 * Agents but only while the palette is CLOSED and focus is not in an editable
 * surface, so it never hijacks native Select-All (or select-all inside any
 * field). Esc and the in-palette grammar (↵ →/← ⌫) are owned by the palette
 * itself, where it can scope propagation away from the canvas listeners.
 */
export function useLauncherHotkeys({
  toggleRoot,
  openAgents,
  isOpen,
}: LauncherHotkeyHandlers): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "k") {
        event.preventDefault();
        toggleRoot();
        return;
      }
      if (key === "a" && !isOpen()) {
        // Yield ⌘A to native Select-All while typing; only claim it as the
        // Agents accelerator when nothing editable is focused.
        if (isEditableTarget(event.target)) return;
        event.preventDefault();
        openAgents();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleRoot, openAgents, isOpen]);
}
