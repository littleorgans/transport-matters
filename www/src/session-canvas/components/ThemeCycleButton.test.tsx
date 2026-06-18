import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../../stores/themeStore";
import { presetThemes } from "../../theme/presets";
import { ThemeCycleButton } from "./ThemeCycleButton";

const openWater = presetThemes.find((theme) => theme.id === "open-water");
if (!openWater) throw new Error("expected open-water preset");

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

describe("ThemeCycleButton", () => {
  it("cycles through every preset plus none and wraps to open-water", () => {
    render(<ThemeCycleButton />);
    const button = screen.getByRole("button", { name: "Theme: none" });
    const expectedStops = [
      openWater,
      ...presetThemes.filter((theme) => theme.id !== openWater.id),
      null,
      openWater,
    ];

    for (const stop of expectedStops) {
      fireEvent.click(button);
      expect(useThemeStore.getState().theme?.id ?? null).toBe(stop?.id ?? null);
      expect(button).toHaveTextContent(`Theme: ${stop?.name ?? "none"}`);
    }
  });

  it("restarts the cycle from open-water for an unknown active theme", () => {
    useThemeStore.setState({ theme: { ...openWater, id: "custom", name: "Custom" } });
    render(<ThemeCycleButton />);

    fireEvent.click(screen.getByRole("button", { name: "Theme: Custom" }));
    expect(useThemeStore.getState().theme?.id).toBe(openWater.id);
  });
});
