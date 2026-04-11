import { create } from "zustand";
import type { PausedFlow } from "../types";

type Tab = "log" | "rules";

interface UIState {
  selectedId: string | null;
  activeTab: Tab;
  pausedFlow: PausedFlow | null;
  setSelectedId: (id: string | null) => void;
  setActiveTab: (tab: Tab) => void;
  setPausedFlow: (flow: PausedFlow | null) => void;
  clearPausedFlow: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  selectedId: null,
  activeTab: "log",
  pausedFlow: null,
  setSelectedId: (id) => set({ selectedId: id }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setPausedFlow: (flow) => set({ pausedFlow: flow }),
  clearPausedFlow: () => set({ pausedFlow: null }),
}));
