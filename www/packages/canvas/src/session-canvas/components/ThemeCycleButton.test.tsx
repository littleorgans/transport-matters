import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../../stores/themeStore";
import { presetThemes } from "../../theme/presets";
import { ThemeCycleButton } from "./ThemeCycleButton";

const openWater = presetThemes.find((theme) => theme.id === "open-water");
if (!openWater) throw new Error("expected open-water preset");

const cyclePresetStops = [openWater, ...presetThemes.filter((theme) => theme.id !== openWater.id)];

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

describe("ThemeCycleButton", () => {
  it("cycles through presets, then NONE, then wraps", () => {
    render(<ThemeCycleButton />);
    const button = screen.getByRole("button", { name: "Theme: NONE" });

    for (const preset of cyclePresetStops) {
      fireEvent.click(button);
      expect(useThemeStore.getState().theme?.id).toBe(preset.id);
      expect(button).toHaveTextContent(`Theme: ${preset.name}`);
    }

    fireEvent.click(button);
    expect(useThemeStore.getState().theme).toBeNull();
    expect(button).toHaveTextContent("Theme: NONE");

    fireEvent.click(button);
    expect(useThemeStore.getState().theme?.id).toBe(openWater.id);
  });

  it("restarts the cycle from the default preset for an unknown active theme", () => {
    const first = presetThemes[0];
    if (!first) throw new Error("expected bundled presets");
    useThemeStore.setState({ theme: { ...first, id: "custom", name: "Custom" } });
    render(<ThemeCycleButton />);

    fireEvent.click(screen.getByRole("button", { name: "Theme: Custom" }));
    expect(useThemeStore.getState().theme?.id).toBe(openWater.id);
  });
});
