import { isRecord } from "../lib/isRecord";
import { normalizeLegacyTheme } from "./migrate";
import type { AmbientSceneRegistry, SceneParamId, ThemePhotoLookup } from "./types";
import {
  ACCENT_IDS,
  type AccentId,
  BORDER_IDS,
  type BorderId,
  CORNER_IDS,
  type CornerId,
  cloneThemeDefinition,
  type ImportErrorCause,
  type ImportResult,
  type OklchAccent,
  SHADOW_IDS,
  type ShadowId,
  THEME_LIMITS,
  THEME_SCHEMA_VERSION,
  THEME_SOURCES,
  type ThemeAccent,
  type ThemeDefinition,
  type ThemeSettings,
} from "./types";

export type ThemeValidationResult = ImportResult;

export interface ThemeValidationDeps {
  sceneRegistry: AmbientSceneRegistry;
  photoLookup: ThemePhotoLookup;
}

const hasOwn = (value: object, key: string): boolean => Object.hasOwn(value, key);

export const validationError = (cause: ImportErrorCause): ThemeValidationResult => ({
  ok: false,
  error: { cause, message: cause },
});

const invalid = (path: string): ThemeValidationResult => validationError(`invalid field: ${path}`);
const missing = (path: string): ThemeValidationResult => validationError(`missing field: ${path}`);
const outOfRange = (path: string): ThemeValidationResult =>
  validationError(`out of range: ${path}`);

const requireField = (record: Record<string, unknown>, path: string, key: string) =>
  hasOwn(record, key) ? null : missing(path);

const isKnown = <T extends string>(values: readonly T[], value: string): value is T =>
  values.includes(value as T);

const validateNumber = (value: unknown, path: string): ThemeValidationResult | null =>
  typeof value === "number" && Number.isFinite(value) ? null : invalid(path);

const validateRange = (
  value: number,
  path: string,
  min: number,
  max: number,
): ThemeValidationResult | null => (value >= min && value <= max ? null : outOfRange(path));

const validateSceneParams = (
  sceneId: string,
  sceneParams: Record<string, unknown>,
  sceneRegistry: AmbientSceneRegistry,
): ThemeValidationResult | null => {
  for (const [paramId, value] of Object.entries(sceneParams)) {
    const numberError = validateNumber(value, `settings.sceneParams.${paramId}`);
    if (numberError) return numberError;

    const metadata = sceneRegistry.paramFor(sceneId, paramId);
    if (!metadata) return validationError(`unknown scene param: ${paramId}`);

    const rangeError = validateRange(
      value as number,
      `sceneParams.${paramId}`,
      metadata.min,
      metadata.max,
    );
    if (rangeError) return rangeError;
  }
  return null;
};

const validateOklch = (value: unknown): ThemeValidationResult | null => {
  if (!isRecord(value)) return invalid("settings.accent.oklch");

  for (const key of ["l", "c", "h"] as const) {
    if (!hasOwn(value, key)) return invalid("settings.accent.oklch");
    const numberError = validateNumber(value[key], `settings.accent.oklch.${key}`);
    if (numberError) return invalid("settings.accent.oklch");

    const limit = THEME_LIMITS.oklch[key];
    const rangeError = validateRange(
      value[key] as number,
      `settings.accent.oklch.${key}`,
      limit.min,
      limit.max,
    );
    if (rangeError) return rangeError;
  }
  return null;
};

const validateAccent = (value: unknown): ThemeValidationResult | null => {
  if (!isRecord(value)) return invalid("settings.accent");

  const hasId = hasOwn(value, "id");
  const hasOklch = hasOwn(value, "oklch");
  if (hasId === hasOklch) return invalid("settings.accent");

  if (hasId) {
    const id = value.id;
    if (typeof id !== "string") return invalid("settings.accent.id");
    return isKnown(ACCENT_IDS, id) ? null : validationError(`unknown accent: ${id}`);
  }

  return validateOklch(value.oklch);
};

const normalizeAccent = (accent: Record<string, unknown>): ThemeAccent =>
  hasOwn(accent, "id")
    ? { id: accent.id as AccentId }
    : { oklch: { ...(accent.oklch as OklchAccent) } };

const normalizeTheme = (
  value: Record<string, unknown>,
  settings: Record<string, unknown>,
): ThemeDefinition => {
  const author = value.author;
  const theme: ThemeDefinition = {
    schema: THEME_SCHEMA_VERSION,
    id: value.id as string,
    name: value.name as string,
    source: value.source as ThemeDefinition["source"],
    settings: {
      sceneId: settings.sceneId as string,
      sceneParams: { ...(settings.sceneParams as Record<SceneParamId, number>) },
      photoKey: settings.photoKey as string,
      accent: normalizeAccent(settings.accent as Record<string, unknown>),
      cornerId: settings.cornerId as CornerId,
      veil: settings.veil as number,
      borderId: settings.borderId as BorderId,
      glass: settings.glass as boolean,
      glassAmount: settings.glassAmount as number,
      shadowId: settings.shadowId as ShadowId,
    },
  };

  if (typeof author === "string") theme.author = author;
  return cloneThemeDefinition(theme);
};

export const validateThemeDefinition = (
  input: unknown,
  deps: ThemeValidationDeps,
): ThemeValidationResult => {
  // Rewrite legacy sceneIds before any field check, so both seams that funnel
  // here (preset load, JSON import) accept a theme on a collapsed scene id.
  const value = normalizeLegacyTheme(input);
  if (!isRecord(value)) return validationError("invalid theme object");
  if (!hasOwn(value, "schema")) return missing("schema");
  if (value.schema !== THEME_SCHEMA_VERSION) return validationError("unsupported schema version");

  for (const path of ["id", "name", "source", "settings"] as const) {
    const fieldError = requireField(value, path, path);
    if (fieldError) return fieldError;
  }

  if (typeof value.id !== "string") return invalid("id");
  if (typeof value.name !== "string") return invalid("name");
  if (typeof value.source !== "string" || !isKnown(THEME_SOURCES, value.source))
    return invalid("source");
  if (hasOwn(value, "author") && typeof value.author !== "string") return invalid("author");
  if (!isRecord(value.settings)) return invalid("settings");

  const settings = value.settings;
  for (const key of [
    "sceneId",
    "sceneParams",
    "photoKey",
    "accent",
    "cornerId",
    "veil",
    "borderId",
    "glass",
    "glassAmount",
    "shadowId",
  ] as const) {
    const fieldError = requireField(settings, `settings.${key}`, key);
    if (fieldError) return fieldError;
  }

  if (typeof settings.sceneId !== "string") return invalid("settings.sceneId");
  if (!deps.sceneRegistry.has(settings.sceneId))
    return validationError(`unknown scene: ${settings.sceneId}`);
  if (!isRecord(settings.sceneParams)) return invalid("settings.sceneParams");

  const paramsError = validateSceneParams(
    settings.sceneId,
    settings.sceneParams,
    deps.sceneRegistry,
  );
  if (paramsError) return paramsError;

  if (typeof settings.photoKey !== "string") return invalid("settings.photoKey");
  if (!deps.photoLookup.getPhoto(settings.photoKey))
    return validationError(`unknown photo: ${settings.photoKey}`);

  const accentError = validateAccent(settings.accent);
  if (accentError) return accentError;

  if (typeof settings.cornerId !== "string") return invalid("settings.cornerId");
  if (!isKnown(CORNER_IDS, settings.cornerId))
    return validationError(`unknown corner: ${settings.cornerId}`);

  const veilError = validateNumber(settings.veil, "settings.veil");
  if (veilError) return veilError;
  const veil = settings.veil as number;
  const veilRangeError = validateRange(veil, "veil", THEME_LIMITS.veil.min, THEME_LIMITS.veil.max);
  if (veilRangeError) return veilRangeError;

  if (typeof settings.borderId !== "string") return invalid("settings.borderId");
  if (!isKnown(BORDER_IDS, settings.borderId))
    return validationError(`unknown border: ${settings.borderId}`);
  if (typeof settings.glass !== "boolean") return invalid("settings.glass");

  const glassError = validateNumber(settings.glassAmount, "settings.glassAmount");
  if (glassError) return glassError;
  const glassAmount = settings.glassAmount as number;
  const glassRangeError = validateRange(
    glassAmount,
    "glassAmount",
    THEME_LIMITS.glassAmount.min,
    THEME_LIMITS.glassAmount.max,
  );
  if (glassRangeError) return glassRangeError;

  if (typeof settings.shadowId !== "string") return invalid("settings.shadowId");
  if (!isKnown(SHADOW_IDS, settings.shadowId))
    return validationError(`unknown shadow: ${settings.shadowId}`);

  return { ok: true, theme: normalizeTheme(value, settings as unknown as Record<string, unknown>) };
};

export const validateThemeSettings = (
  settings: ThemeSettings,
  deps: ThemeValidationDeps,
): ThemeValidationResult =>
  validateThemeDefinition(
    {
      schema: THEME_SCHEMA_VERSION,
      id: "__draft__",
      name: "Draft",
      source: "user",
      settings,
    },
    deps,
  );
