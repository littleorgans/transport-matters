import { useCallback, useEffect, useState } from "react";

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

  useEffect(() => {
    if (!isFullscreen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeFullscreen();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isFullscreen, closeFullscreen]);

  return {
    isFullscreen,
    openFullscreen,
    closeFullscreen,
  };
}
