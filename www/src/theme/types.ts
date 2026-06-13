import type { PhotoEntry } from "../ambient/photos";
import type { AmbientSceneParamMetadata, AmbientSceneRegistry } from "../ambient/sceneRegistry";

export const THEME_SCHEMA_VERSION = 1 as const;
export type ThemeSchema = typeof THEME_SCHEMA_VERSION;
export type ThemeSource = "curated" | "user" | "community";
export type ThemeId = string;
export type SceneId = string;
export type SceneParamId = string;
export type PhotoKey = string;
export type AccentId = "ivory" | "sage" | "sky" | "amber" | "rose" | "lavender";
export type CornerId = "none" | "small" | "medium" | "large";
export type BorderId = "hairline" | "standard" | "strong";
export type ShadowId = "flat" | "standard" | "deep";

export interface OklchAccent {
  l: number;
  c: number;
  h: number;
}

export type ThemeAccent = { id: AccentId } | { oklch: OklchAccent };

export interface ThemeSettings {
  sceneId: SceneId;
  sceneParams: Record<SceneParamId, number>;
  photoKey: PhotoKey;
  accent: ThemeAccent;
  cornerId: CornerId;
  veil: number;
  borderId: BorderId;
  glass: boolean;
  glassAmount: number;
  shadowId: ShadowId;
}

export interface ThemeDefinition {
  schema: ThemeSchema;
  id: ThemeId;
  name: string;
  author?: string;
  source: ThemeSource;
  settings: ThemeSettings;
}

export interface ThemeRegistryEntry {
  theme: ThemeDefinition;
  mutable: boolean;
  deletable: boolean;
  duplicatedFrom?: ThemeId;
}

export interface ThemeRegistrySnapshot {
  activeThemeId: ThemeId;
  draftSettings: ThemeSettings;
  /** Active entry's original settings (slider baseline ticks); null when none is active. */
  baselineSettings: ThemeSettings | null;
  dirty: boolean;
  themes: ThemeRegistryEntry[];
}

export type ImportErrorCause =
  | "invalid json"
  | "invalid theme object"
  | "unsupported schema version"
  | `missing field: ${string}`
  | `invalid field: ${string}`
  | `unknown scene: ${string}`
  | `unknown scene param: ${string}`
  | `out of range: ${string}`
  | `unknown photo: ${string}`
  | `unknown accent: ${string}`
  | `unknown corner: ${string}`
  | `unknown border: ${string}`
  | `unknown shadow: ${string}`
  | "storage write failed";

export type ImportResult =
  | { ok: true; theme: ThemeDefinition }
  | { ok: false; error: { cause: ImportErrorCause; message: string } };

export type ThemeDraftUpdateResult =
  | { ok: true }
  | { ok: false; error: { cause: ImportErrorCause; message: string } };

export const ACCENTS: Record<AccentId, { label: string; hex: string; rgb: string }> = {
  ivory: { label: "Ivory", hex: "#e8e4dc", rgb: "232 228 220" },
  sage: { label: "Sage", hex: "#7ec9a0", rgb: "126 201 160" },
  sky: { label: "Sky", hex: "#7ab3d4", rgb: "122 179 212" },
  amber: { label: "Amber", hex: "#d4b07e", rgb: "212 176 126" },
  rose: { label: "Rose", hex: "#d4879c", rgb: "212 135 156" },
  lavender: { label: "Lavender", hex: "#a88bda", rgb: "168 139 218" },
};

export const CORNERS: Record<CornerId, { label: string; px: number }> = {
  none: { label: "None", px: 0 },
  small: { label: "S", px: 6 },
  medium: { label: "M", px: 12 },
  large: { label: "L", px: 20 },
};

export const BORDERS: Record<BorderId, { label: string; color: string }> = {
  hairline: { label: "Hairline", color: "rgb(255 255 255 / 0.10)" },
  standard: { label: "Standard", color: "#2d2d2d" },
  strong: { label: "Strong", color: "#454545" },
};

export const SHADOWS: Record<ShadowId, { label: string; value: string }> = {
  flat: { label: "Flat", value: "none" },
  standard: { label: "Standard", value: "0 22px 70px rgb(0 0 0 / 0.46)" },
  deep: { label: "Deep", value: "0 30px 90px rgb(0 0 0 / 0.62)" },
};

export const ACCENT_IDS = Object.keys(ACCENTS) as AccentId[];
export const CORNER_IDS = Object.keys(CORNERS) as CornerId[];
export const BORDER_IDS = Object.keys(BORDERS) as BorderId[];
export const SHADOW_IDS = Object.keys(SHADOWS) as ShadowId[];
export const THEME_SOURCES: ThemeSource[] = ["curated", "user", "community"];

export const THEME_LIMITS = {
  veil: { min: 0.35, max: 0.95 },
  glassAmount: { min: 4, max: 32 },
  oklch: {
    l: { min: 0.62, max: 0.88 },
    c: { min: 0.02, max: 0.18 },
    h: { min: 0, max: 360 },
  },
} as const;

export const ACCENT_BAND = { l: 0.74, c: 0.12, h: { min: 0, max: 360 } } as const;

export const accentCss = (accent: ThemeAccent): string =>
  "id" in accent
    ? ACCENTS[accent.id].hex
    : `oklch(${accent.oklch.l} ${accent.oklch.c} ${accent.oklch.h})`;

export type { AmbientSceneParamMetadata, AmbientSceneRegistry };

export interface ThemePhotoLookup {
  getPhoto(key: PhotoKey): PhotoEntry | null;
  defaultPhotoKey(): PhotoKey;
  photoKeyAt(index: number): PhotoKey | null;
}

export const THEME_DEFAULT_PHOTO_KEY = "picsum:102";

export const createPhotoLookup = (catalog: readonly PhotoEntry[]): ThemePhotoLookup => {
  const photoByKey = new Map(catalog.map((photo) => [photo.key, photo]));
  return {
    getPhoto: (key) => photoByKey.get(key) ?? null,
    defaultPhotoKey: () =>
      photoByKey.get(THEME_DEFAULT_PHOTO_KEY)?.key ?? catalog[0]?.key ?? THEME_DEFAULT_PHOTO_KEY,
    photoKeyAt: (index) => catalog[index]?.key ?? null,
  };
};

export interface ThemeStorageRecordV1 {
  schema: 1;
  activeThemeId: ThemeId | null;
  themes: ThemeDefinition[];
}

export interface ThemeStorage {
  load(): ThemeStorageRecordV1;
  save(record: ThemeStorageRecordV1): void;
}

export const cloneThemeAccent = (accent: ThemeAccent): ThemeAccent =>
  "id" in accent ? { id: accent.id } : { oklch: { ...accent.oklch } };

export const cloneThemeSettings = (settings: ThemeSettings): ThemeSettings => ({
  ...settings,
  sceneParams: { ...settings.sceneParams },
  accent: cloneThemeAccent(settings.accent),
});

export const cloneThemeDefinition = (theme: ThemeDefinition): ThemeDefinition => ({
  ...theme,
  settings: cloneThemeSettings(theme.settings),
});

/**
 * Narrows an unknown to a plain object (excludes arrays and null). Shared by
 * the theme validation and migration seams so the guard has a single owner.
 */
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
