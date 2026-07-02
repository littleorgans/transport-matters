import type { ReactNode } from "react";
import { CloseIcon } from "./icons";

interface FullscreenOverlayProps {
  children: ReactNode;
  label: string;
  onClose: () => void;
  isOpen: boolean;
  inlineWhenClosed?: boolean;
}

/**
 * Wraps content that can be toggled into a viewport-covering overlay.
 *
 * The element structure is identical across both states; only the
 * classNames flip. That stability is load-bearing: the breakpoint editor
 * panes hold local edit state, so the single instance must never unmount
 * when toggling fullscreen.
 *
 * When closed-inline, both wrappers are `display: contents` so they emit no
 * box at all — children keep their parent's flex context, and a
 * `flex-1 overflow-y-auto` pane scrolls exactly as it did before being
 * wrapped. When open, the outer wrapper is a fixed, viewport-covering flex
 * column whose inner region scrolls, so tall payloads never clip.
 */
export function FullscreenOverlay({
  children,
  label,
  onClose,
  isOpen,
  inlineWhenClosed = false,
}: FullscreenOverlayProps) {
  if (!isOpen && !inlineWhenClosed) return null;

  return (
    <div className={isOpen ? "fixed inset-0 z-50 flex flex-col bg-canvas" : "contents"}>
      <button
        type="button"
        onClick={onClose}
        aria-label={label}
        aria-hidden={!isOpen}
        tabIndex={isOpen ? 0 : -1}
        className={
          isOpen
            ? "btn absolute right-4 top-4 z-10 cursor-pointer border border-edge bg-surface px-2.5 py-2 text-txt transition-colors hover:bg-raised hover:text-txt"
            : "hidden"
        }
      >
        <CloseIcon className="h-3 w-3" />
      </button>
      <div className={isOpen ? "flex min-h-0 flex-1 flex-col overflow-y-auto pt-16" : "contents"}>
        {children}
      </div>
    </div>
  );
}
