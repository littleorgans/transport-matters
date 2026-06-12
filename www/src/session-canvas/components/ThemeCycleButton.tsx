import { useThemeStore } from "../../stores/themeStore";
import { presetThemes } from "../../theme/presets";

/**
 * Cycles the active theme: unthemed, then each bundled preset in order, then
 * back to unthemed. The minimal v1 affordance until a real picker ships;
 * reads and writes the theme store directly so the command bar stays dumb.
 */
export function ThemeCycleButton() {
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);
  const clearTheme = useThemeStore((state) => state.clearTheme);

  const cycle = () => {
    const next = presetThemes[presetThemes.findIndex((preset) => preset.id === theme?.id) + 1];
    if (next) {
      setTheme(next);
    } else {
      clearTheme();
    }
  };

  return (
    <button className="canvas-button" onClick={cycle} type="button">
      Theme: {theme?.name ?? "none"}
    </button>
  );
}
