import type { ImportResult, ThemeDefinition } from "./types";
import { type ThemeValidationDeps, validateThemeDefinition, validationError } from "./validate";

export const serializeTheme = (theme: ThemeDefinition): string =>
  `${JSON.stringify(theme, null, 2)}\n`;

export const parseThemeJson = (json: string, deps: ThemeValidationDeps): ImportResult => {
  let value: unknown;

  try {
    value = JSON.parse(json);
  } catch {
    return validationError("invalid json");
  }

  return validateThemeDefinition(value, deps);
};
