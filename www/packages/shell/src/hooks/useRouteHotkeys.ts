import { isEditableTarget } from "@tm/core/keybindings";
import { useEffect } from "react";
import type { Route } from "../stores/uiStore";
import { useUIStore } from "../stores/uiStore";

/**
 * Global keybindings for route switching.
 *
 *   1 / 2 / 3 / 4      → INTERCEPT / OVERLAYS / TRACE / RECALL
 *   g then i/o/t/r     → same, vim-style leader-prefix
 *
 * The leader variant exists so users with digit-press fatigue (or digit
 * collisions with in-flight forms) can still switch. The leader must fire
 * within 900ms of `g` or it resets. Typing in any input, textarea, or
 * contenteditable element suspends the hotkeys entirely.
 */
export function useRouteHotkeys() {
  const setActiveRoute = useUIStore((s) => s.setActiveRoute);

  useEffect(() => {
    let leaderArmed = false;
    let leaderTimer: ReturnType<typeof setTimeout> | null = null;

    const clearLeader = () => {
      leaderArmed = false;
      if (leaderTimer) {
        clearTimeout(leaderTimer);
        leaderTimer = null;
      }
    };

    const handler = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // Digit shortcuts
      const digitRoute: Record<string, Route> = {
        "1": "intercept",
        "2": "overlays",
        "3": "trace",
        "4": "recall",
      };
      const digitMatch = digitRoute[e.key];
      if (digitMatch) {
        e.preventDefault();
        setActiveRoute(digitMatch);
        clearLeader();
        return;
      }

      // Leader-prefix shortcuts
      if (leaderArmed) {
        const leaderRoute: Record<string, Route> = {
          i: "intercept",
          o: "overlays",
          t: "trace",
          r: "recall",
        };
        const leaderMatch = leaderRoute[e.key.toLowerCase()];
        if (leaderMatch) {
          e.preventDefault();
          setActiveRoute(leaderMatch);
        }
        clearLeader();
        return;
      }

      if (e.key === "g") {
        leaderArmed = true;
        leaderTimer = setTimeout(clearLeader, 900);
      }
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      clearLeader();
    };
  }, [setActiveRoute]);
}
