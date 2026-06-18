import { useEffect } from "react";
import { isEditableTarget } from "../../lib/domFocus";
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
 * Renderer-level keydown dispatcher for the command center (NOT Electron
 * globalShortcut — the palette is renderer chrome). ⌘K toggles root; ⌘A jumps to
 * Agents but only while the palette is CLOSED and focus is not in an editable
 * surface, so it never hijacks native Select-All; ⌘, jumps to Settings from
 * anywhere (no native conflict). Esc and the in-palette grammar (↵ →/← ⌫) are
 * owned by the palette itself, where it can scope propagation away from the
 * canvas listeners.
 */
export function useLauncherHotkeys({
  toggleRoot,
  openScope,
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
        openScope("agents");
        return;
      }
      if (key === ",") {
        // ⌘, has no native text-editing role, so it jumps to Settings from
        // anywhere (including while typing a query).
        event.preventDefault();
        openScope("settings");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleRoot, openScope, isOpen]);
}
