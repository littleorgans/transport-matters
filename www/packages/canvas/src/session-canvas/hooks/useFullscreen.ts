import { useCallback, useState } from "react";
import { useFullscreenKeybindings } from "../../keybindings/engine";

interface UseFullscreenOptions {
  onClose?: () => void;
}

interface FullscreenState {
  isFullscreen: boolean;
  openFullscreen: () => void;
  closeFullscreen: () => void;
}

/**
 * Canvas-owned fullscreen state registered with the keybinding engine, so
 * Escape respects launcher and dock priority inside canvas routes. The
 * inspector has its own engine-free variant in `hooks/useFullscreen.ts`.
 */
export function useFullscreen({ onClose }: UseFullscreenOptions = {}): FullscreenState {
  const [isFullscreen, setIsFullscreen] = useState(false);

  const openFullscreen = useCallback(() => setIsFullscreen(true), []);

  const closeFullscreen = useCallback(() => {
    setIsFullscreen(false);
    onClose?.();
  }, [onClose]);

  useFullscreenKeybindings({ close: closeFullscreen, isOpen: () => isFullscreen });

  return {
    isFullscreen,
    openFullscreen,
    closeFullscreen,
  };
}
