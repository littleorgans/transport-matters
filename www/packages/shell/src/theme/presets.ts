/**
 * Bundled curated themes, authored in little-background-lab and exported as
 * canonical JSON (serializeTheme). Each preset is validated against the live
 * scene registry and photo catalog at module init: a preset that drifts from
 * the contract fails loudly in dev and tests instead of silently misrendering.
 */
import { themeValidationDeps } from "./deps";
import littleorgans from "./presets/littleorgans.json";
import openWater from "./presets/open-water.json";
import type { ThemeDefinition, ThemeId } from "./types";
import { validateThemeDefinition } from "./validate";

const rawPresets: unknown[] = [littleorgans, openWater];

export const presetThemes: ThemeDefinition[] = rawPresets.map((raw) => {
  const result = validateThemeDefinition(raw, themeValidationDeps);
  if (!result.ok) {
    throw new Error(
      `invalid bundled theme preset (${result.error.cause}): ${result.error.message}`,
    );
  }
  return result.theme;
});

export const presetTheme = (id: ThemeId): ThemeDefinition | undefined =>
  presetThemes.find((theme) => theme.id === id);
