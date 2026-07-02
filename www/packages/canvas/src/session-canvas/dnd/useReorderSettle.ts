import { useCallback, useEffect, useRef, useState } from "react";
import { LAYOUT_MOTION_MS } from "../../engine";

export function useReorderSettle() {
  const [reorderActive, setReorderActive] = useState(false);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearSettleTimer = useCallback(() => {
    if (settleTimer.current === null) return;
    clearTimeout(settleTimer.current);
    settleTimer.current = null;
  }, []);

  const markReorderActive = useCallback(
    (active: boolean) => {
      clearSettleTimer();
      setReorderActive(active);
    },
    [clearSettleTimer],
  );

  const finishReorder = useCallback(
    (settle: boolean) => {
      clearSettleTimer();
      if (!settle) {
        setReorderActive(false);
        return;
      }
      setReorderActive(true);
      settleTimer.current = setTimeout(() => {
        settleTimer.current = null;
        setReorderActive(false);
      }, LAYOUT_MOTION_MS);
    },
    [clearSettleTimer],
  );

  useEffect(() => clearSettleTimer, [clearSettleTimer]);

  return { reorderActive, markReorderActive, finishReorder };
}
