import type { ReactNode } from "react";
import { CloseIcon } from "./icons";

interface FullscreenOverlayProps {
  children: ReactNode;
  label: string;
  onClose: () => void;
  isOpen: boolean;
  inlineWhenClosed?: boolean;
}

export function FullscreenOverlay({
  children,
  label,
  onClose,
  isOpen,
  inlineWhenClosed = false,
}: FullscreenOverlayProps) {
  if (!isOpen && !inlineWhenClosed) return null;

  return (
    <div
      className={`relative min-h-0 ${
        isOpen ? "fixed inset-0 z-50 bg-canvas flex flex-col overflow-hidden" : "flex flex-1"
      }`}
    >
      <button
        type="button"
        onClick={() => {
          if (isOpen) onClose();
        }}
        aria-label={label}
        aria-hidden={!isOpen}
        tabIndex={isOpen ? 0 : -1}
        className={`absolute right-4 top-4 border border-edge bg-surface px-2.5 py-2 text-txt transition-colors hover:bg-raised hover:text-txt ${
          isOpen ? "btn cursor-pointer" : "pointer-events-none opacity-0"
        }`}
      >
        <CloseIcon className="h-3 w-3" />
      </button>
      <div className={`flex-1 min-h-0 ${isOpen ? "pt-16" : ""}`}>{children}</div>
    </div>
  );
}
