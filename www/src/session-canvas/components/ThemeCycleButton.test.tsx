import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../../stores/themeStore";
import { presetThemes } from "../../theme/presets";
import { ThemeCycleButton } from "./ThemeCycleButton";

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

describe("ThemeCycleButton", () => {
  it("cycles unthemed through every preset and wraps to the first preset", () => {
    render(<ThemeCycleButton />);
    const button = screen.getByRole("button", { name: "Theme: none" });

    for (const preset of presetThemes) {
      fireEvent.click(button);
      expect(useThemeStore.getState().theme?.id).toBe(preset.id);
      expect(button).toHaveTextContent(`Theme: ${preset.name}`);
    }

    fireEvent.click(button);
    expect(useThemeStore.getState().theme?.id).toBe(presetThemes[0]?.id);
    expect(button).toHaveTextContent(`Theme: ${presetThemes[0]?.name}`);
  });

  it("restarts the cycle from the first preset for an unknown active theme", () => {
    const first = presetThemes[0];
    if (!first) throw new Error("expected bundled presets");
    useThemeStore.setState({ theme: { ...first, id: "custom", name: "Custom" } });
    render(<ThemeCycleButton />);

    fireEvent.click(screen.getByRole("button", { name: "Theme: Custom" }));
    expect(useThemeStore.getState().theme?.id).toBe(first.id);
  });
});
