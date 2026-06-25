import { type KeyboardEvent, useCallback, useEffect } from "react";
import { advanceGesture, type CommandRow, type Lifecycle, type RowAction } from "./commandModel";

interface LauncherInputKeysArgs {
  open: boolean;
  close: () => void;
  query: string;
  highlighted: string | undefined;
  rowByValue: Map<string, CommandRow>;
  applyGesture: (row: CommandRow, action: RowAction, lifecycle: Lifecycle) => void;
  canBack: boolean;
  back: () => void;
}

/**
 * The palette's input-level keyboard grammar — sibling to {@link useLauncherHotkeys}
 * (which owns the GLOBAL ⌘K/⌘A opens). Owns the window-capture Escape-to-close and
 * the search input's ArrowRight-advance / ArrowLeft|Backspace-back gestures, so
 * {@link useCommandCenter} stays a thin composition root.
 */
export function useLauncherInputKeys({
  open,
  close,
  query,
  highlighted,
  rowByValue,
  applyGesture,
  canBack,
  back,
}: LauncherInputKeysArgs): (event: KeyboardEvent<HTMLInputElement>) => void {
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

  return useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      const caret = event.currentTarget.selectionStart ?? 0;
      if (event.key === "ArrowRight" && caret >= query.length) {
        const row = highlighted ? rowByValue.get(highlighted) : undefined;
        const advance = row ? advanceGesture(row) : null;
        if (row && advance && advance.lifecycle !== "none") {
          event.preventDefault();
          applyGesture(row, advance.action, advance.lifecycle);
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
}
