import { useCallback, useEffect, useRef, useState } from "react";

interface UseFullscreenOptions {
  onClose?: () => void;
}

interface FullscreenState {
  isFullscreen: boolean;
  openFullscreen: () => void;
  closeFullscreen: () => void;
}

/**
 * Inspector-owned fullscreen state with a window-level Escape fallback.
 *
 * The inspector renders outside any keybinding engine, so Escape handling
 * is a plain window listener active only while fullscreen is open. The
 * canvas has its own engine-registered variant in
 * `session-canvas/hooks/useFullscreen.ts`.
 */
export function useFullscreen({ onClose }: UseFullscreenOptions = {}): FullscreenState {
  const [isFullscreen, setIsFullscreen] = useState(false);

  const openFullscreen = useCallback(() => setIsFullscreen(true), []);

  const closeFullscreen = useCallback(() => {
    setIsFullscreen(false);
    onClose?.();
  }, [onClose]);

  const closeRef = useRef(closeFullscreen);
  closeRef.current = closeFullscreen;

  useEffect(() => {
    if (!isFullscreen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isFullscreen]);

  return {
    isFullscreen,
    openFullscreen,
    closeFullscreen,
  };
}
