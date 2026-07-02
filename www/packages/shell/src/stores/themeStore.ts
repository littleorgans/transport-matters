import { createFrontendPersistStorage, isRecord } from "@tm/core";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { normalizeLegacyTheme } from "../theme/migrate";
import { presetTheme, presetThemes } from "../theme/presets";
import type { ThemeDefinition } from "../theme/types";
import { FRONTEND_STORAGE_KEYS } from "./persistence";

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
   * Advances to the next bundled preset, wrapping past the last preset back to
   * unthemed. The single source of truth for "cycle the look" — shared by the
   * Lab command bar's ThemeCycleButton and the ⌘K command center's Theme entry.
   */
  cycleTheme: () => void;
  /**
   * Tunes one scene param (e.g. dayProgress) on the active theme. The value
   * lives in settings.sceneParams, so it persists and round-trips through the
   * canonical export format like any other theme field. No-op while unthemed.
   */
  setSceneParam: (paramId: string, value: number) => void;
  /**
   * When true (the default), scenes with a dayProgress param track the real
   * local clock instead of the stored baseline. A runtime preference, not
   * theme data: the live value never enters settings.sceneParams.
   */
  liveDayCycle: boolean;
  setLiveDayCycle: (value: boolean) => void;
}

/** The slice the store persists: theme data plus the runtime day-cycle flag. */
type PersistedThemeSlice = Pick<ThemeState, "theme" | "liveDayCycle">;

/** Out-of-the-box default, reused for boot and for resetting bad payloads. */
const defaultPersistedSlice = (): PersistedThemeSlice => ({
  theme: presetTheme("open-water") ?? null,
  liveDayCycle: true,
});

const defaultCycleTheme = presetTheme("open-water");
const cycleThemeStops: readonly (ThemeDefinition | null)[] = [
  ...(defaultCycleTheme
    ? [defaultCycleTheme, ...presetThemes.filter((theme) => theme.id !== defaultCycleTheme.id)]
    : presetThemes),
  null,
];

const nextPresetTheme = (theme: ThemeDefinition | null): ThemeDefinition | null => {
  const currentIndex = cycleThemeStops.findIndex((stop) => stop?.id === theme?.id);
  const nextIndex = (currentIndex + 1) % cycleThemeStops.length;
  return cycleThemeStops[nextIndex] ?? null;
};

/**
 * Resolves the persisted `theme` field. `null` is a real choice (explicit
 * unthemed) and survives; a record is trusted verbatim (matching the store's
 * no-revalidation contract) after legacy sceneId collapses are rewritten (e.g.
 * reference-sea-ii -> reference-sea). Anything else — `undefined`, an absent
 * key, or a primitive — is not a usable theme, so it resets to the default
 * rather than letting `theme: undefined` (an invalid state value) reach the UI.
 */
const migrateTheme = (value: unknown): ThemeDefinition | null => {
  if (value === null) return null;
  if (isRecord(value)) return normalizeLegacyTheme(value) as ThemeDefinition;
  return defaultPersistedSlice().theme;
};

/**
 * Rehydration migrate for the persisted theme slice. The persisted store
 * trusts its record verbatim, so a payload that is absent (first load after a
 * version bump) or malformed (corrupted, hand-edited, or written by an
 * incompatible build) must not crash rehydration by reaching into nested
 * fields, nor surface an invalid `theme`. A non-record payload resets wholesale
 * to the out-of-the-box default; a record has its theme and day-cycle flag
 * each resolved and defaulted independently.
 */
export const migrateThemeState = (persisted: unknown): PersistedThemeSlice => {
  if (!isRecord(persisted)) return defaultPersistedSlice();
  return {
    theme: migrateTheme(persisted.theme),
    liveDayCycle: typeof persisted.liveDayCycle === "boolean" ? persisted.liveDayCycle : true,
  };
};

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      // Open water is the out-of-the-box look; a persisted choice (including
      // an explicit "none") rehydrates over this and wins.
      theme: defaultPersistedSlice().theme,
      setTheme: (theme) => set({ theme }),
      clearTheme: () => set({ theme: null }),
      cycleTheme: () =>
        set((state) => ({
          theme: nextPresetTheme(state.theme),
        })),
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
      liveDayCycle: true,
      setLiveDayCycle: (value) => set({ liveDayCycle: value }),
    }),
    {
      name: FRONTEND_STORAGE_KEYS.themeStore,
      storage: createFrontendPersistStorage(),
      // The persisted store trusts its record verbatim (no re-validation on
      // load), so a stored theme on a collapsed scene id would reach the
      // renderer unrewritten. migrateThemeState normalizes it here, the third
      // persistence seam alongside validateThemeDefinition's two, and guards
      // absent or malformed payloads so rehydration never throws.
      version: 1,
      migrate: migrateThemeState,
      partialize: (state) => ({ theme: state.theme, liveDayCycle: state.liveDayCycle }),
    },
  ),
);
