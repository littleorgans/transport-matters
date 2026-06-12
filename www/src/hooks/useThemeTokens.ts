import { useEffect } from "react";
import { useThemeStore } from "../stores/themeStore";
import { applyThemeTokens } from "../theme/theme";

/**
 * The seven custom properties applyThemeTokens writes inline on :root.
 * theme.ts is a verbatim port of the lab contract and must not grow
 * www-only members, so the reset list lives here. Keep in sync with
 * applyThemeTokens in src/theme/theme.ts.
 */
const THEME_TOKEN_NAMES = [
  "--color-accent",
  "--accent-rgb",
  "--pane-radius",
  "--pane-surface-alpha",
  "--pane-border-color",
  "--pane-blur",
  "--canvas-pane-shadow",
] as const;

export const clearThemeTokens = (): void => {
  const root = document.documentElement.style;
  for (const name of THEME_TOKEN_NAMES) {
    root.removeProperty(name);
  }
};

/**
 * Keeps the :root theme tokens in sync with the active theme. Mount once at
 * the app root. Inline values win over the stylesheet defaults; clearing the
 * theme removes them so the defaults show through again.
 */
export function useThemeTokens(): void {
  const theme = useThemeStore((state) => state.theme);
  useEffect(() => {
    if (theme) {
      applyThemeTokens(theme.settings);
    } else {
      clearThemeTokens();
    }
  }, [theme]);
}
