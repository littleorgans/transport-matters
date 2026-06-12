import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ThemeDefinition } from "../theme/types";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "./persistence";

/**
 * The active theme. Null means unthemed: every surface falls back to the
 * stylesheet defaults in index.css. The full ThemeDefinition persists (not
 * just an id) so user and community themes survive reloads without a registry.
 */
interface ThemeState {
  theme: ThemeDefinition | null;
  setTheme: (theme: ThemeDefinition) => void;
  clearTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: null,
      setTheme: (theme) => set({ theme }),
      clearTheme: () => set({ theme: null }),
    }),
    {
      name: FRONTEND_STORAGE_KEYS.themeStore,
      storage: createFrontendPersistStorage(),
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);
