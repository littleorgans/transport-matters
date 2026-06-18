import { useThemeStore } from "../../stores/themeStore";

/**
 * Cycles the active theme: unthemed, then each bundled preset in order, then
 * back to unthemed. The minimal v1 affordance until a real picker ships; the
 * cycle transition lives in the theme store (shared with the ⌘K command
 * center's Theme entry) so the command bar stays dumb.
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
