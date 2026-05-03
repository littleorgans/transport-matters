import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PausedFlow } from "../types";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "./persistence";

/**
 * Four lenses on the same exchange stream.
 *
 *   intercept — operator at the wire: watch, breakpoint, tamper, overlay
 *   overlays  — librarian curating persistent transforms across exchanges
 *   trace     — analyst reading a diagram: non-interactive topology of exchanges
 *   recall    — archivist mining history: project session browser
 *
 * Session context travels across routes. A route is a lens, not a workspace.
 */
export type Route = "intercept" | "overlays" | "trace" | "recall";

interface UIState {
  activeRoute: Route;
  selectedId: string | null;
  includeHistory: boolean;
  pausedFlow: PausedFlow | null;
  /** Flow ID awaiting a response after FORWARD. Keeps the editor open with a loading state. */
  forwardingFlowId: string | null;
  /**
   * Milliseconds timestamp of the last SSE event observed for the
   * forwarding flow. Drives the silence-window timeout in
   * BreakpointEditor — stamping a new value makes the effect tear down
   * its timer and start a fresh window. Null when no forward is in
   * flight or no activity has landed yet.
   */
  forwardingLastActivityAt: number | null;
  /** When true, newly-mounted message/system cards start fully expanded. */
  autoExpandBlocks: boolean;
  /** Collapsed track ids keyed by run/session id. */
  collapsedTrackIdsBySession: Record<string, string[]>;
  setActiveRoute: (route: Route) => void;
  setSelectedId: (id: string | null) => void;
  setIncludeHistory: (value: boolean) => void;
  setPausedFlow: (flow: PausedFlow | null) => void;
  clearPausedFlow: () => void;
  setForwardingFlowId: (id: string | null) => void;
  bumpForwardingActivity: () => void;
  setAutoExpandBlocks: (value: boolean) => void;
  toggleCollapsedTrack: (sessionId: string, trackId: string) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      activeRoute: "intercept",
      selectedId: null,
      includeHistory: false,
      pausedFlow: null,
      forwardingFlowId: null,
      forwardingLastActivityAt: null,
      autoExpandBlocks: false,
      collapsedTrackIdsBySession: {},
      setActiveRoute: (route) => set({ activeRoute: route }),
      setSelectedId: (id) => set({ selectedId: id }),
      setIncludeHistory: (value) => set({ includeHistory: value }),
      setPausedFlow: (flow) => set({ pausedFlow: flow }),
      clearPausedFlow: () =>
        set({ pausedFlow: null, forwardingFlowId: null, forwardingLastActivityAt: null }),
      setForwardingFlowId: (id) =>
        set(
          id === null
            ? { forwardingFlowId: null, forwardingLastActivityAt: null }
            : { forwardingFlowId: id },
        ),
      bumpForwardingActivity: () => set({ forwardingLastActivityAt: Date.now() }),
      setAutoExpandBlocks: (value) => set({ autoExpandBlocks: value }),
      toggleCollapsedTrack: (sessionId, trackId) =>
        set((state) => {
          const current = state.collapsedTrackIdsBySession[sessionId] ?? [];
          const next = current.includes(trackId)
            ? current.filter((id) => id !== trackId)
            : [...current, trackId];
          return {
            collapsedTrackIdsBySession: {
              ...state.collapsedTrackIdsBySession,
              [sessionId]: next,
            },
          };
        }),
    }),
    {
      name: FRONTEND_STORAGE_KEYS.uiStore,
      storage: createFrontendPersistStorage(),
      partialize: (state) => ({
        activeRoute: state.activeRoute,
        selectedId: state.selectedId,
        autoExpandBlocks: state.autoExpandBlocks,
        collapsedTrackIdsBySession: state.collapsedTrackIdsBySession,
      }),
    },
  ),
);
