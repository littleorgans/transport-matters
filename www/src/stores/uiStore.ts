import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PausedFlow } from "../types";

interface UIState {
  selectedId: string | null;
  pausedFlow: PausedFlow | null;
  /** Flow ID awaiting a response after FORWARD. Keeps the editor open with a loading state. */
  forwardingFlowId: string | null;
  /** When true, newly-mounted message/system cards start fully expanded. */
  autoExpandBlocks: boolean;
  setSelectedId: (id: string | null) => void;
  setPausedFlow: (flow: PausedFlow | null) => void;
  clearPausedFlow: () => void;
  setForwardingFlowId: (id: string | null) => void;
  setAutoExpandBlocks: (value: boolean) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      selectedId: null,
      pausedFlow: null,
      forwardingFlowId: null,
      autoExpandBlocks: false,
      setSelectedId: (id) => set({ selectedId: id }),
      setPausedFlow: (flow) => set({ pausedFlow: flow }),
      clearPausedFlow: () => set({ pausedFlow: null, forwardingFlowId: null }),
      setForwardingFlowId: (id) => set({ forwardingFlowId: id }),
      setAutoExpandBlocks: (value) => set({ autoExpandBlocks: value }),
    }),
    {
      name: "manicure-ui",
      partialize: (state) => ({
        selectedId: state.selectedId,
        autoExpandBlocks: state.autoExpandBlocks,
      }),
    },
  ),
);
