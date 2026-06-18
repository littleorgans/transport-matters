import { useThemeStore } from "../../stores/themeStore";

/**
 * Cycles the active theme through the same stops as the ⌘K command center.
 * The cycle transition lives in the theme store so the command bar stays dumb.
 */
export function ThemeCycleButton() {
  const theme = useThemeStore((state) => state.theme);
  const cycleTheme = useThemeStore((state) => state.cycleTheme);

  return (
    <button className="canvas-button" onClick={cycleTheme} type="button">
      Theme: {theme?.name ?? "none"}
    </button>
  );
}
