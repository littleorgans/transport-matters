import { useCallback, useState } from "react";
import { useFullscreenKeybindings } from "../keybindings/engine";

interface UseFullscreenOptions {
  onClose?: () => void;
}

interface FullscreenState {
  isFullscreen: boolean;
  openFullscreen: () => void;
  closeFullscreen: () => void;
}

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
