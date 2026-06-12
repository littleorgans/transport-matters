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
  /**
   * Tunes one scene param (e.g. dayProgress) on the active theme. The value
   * lives in settings.sceneParams, so it persists and round-trips through the
   * canonical export format like any other theme field. No-op while unthemed.
   */
  setSceneParam: (paramId: string, value: number) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: null,
      setTheme: (theme) => set({ theme }),
      clearTheme: () => set({ theme: null }),
      setSceneParam: (paramId, value) =>
        set((state) => {
          if (!state.theme) return state;
          return {
            theme: {
              ...state.theme,
              settings: {
                ...state.theme.settings,
                sceneParams: { ...state.theme.settings.sceneParams, [paramId]: value },
              },
            },
          };
        }),
    }),
    {
      name: FRONTEND_STORAGE_KEYS.themeStore,
      storage: createFrontendPersistStorage(),
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);
