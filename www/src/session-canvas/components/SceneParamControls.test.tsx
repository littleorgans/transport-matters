import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useThemeStore } from "../../stores/themeStore";
import { presetTheme } from "../../theme/presets";
import { SceneParamControls } from "./SceneParamControls";

const openWater = presetTheme("open-water");
const littleorgans = presetTheme("littleorgans");
if (!openWater || !littleorgans) throw new Error("expected bundled presets");

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

describe("SceneParamControls", () => {
  it("renders nothing while unthemed", () => {
    const { container } = render(<SceneParamControls />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a scene without params", () => {
    useThemeStore.setState({ theme: littleorgans });
    const { container } = render(<SceneParamControls />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the day slider for a sea scene at the scene default", () => {
    useThemeStore.setState({ theme: openWater });
    render(<SceneParamControls />);
    const slider = screen.getByRole("slider", { name: "Scene day" });
    expect(slider).toHaveValue("0.25");
  });

  it("scrubbing writes the param through the store", () => {
    useThemeStore.setState({ theme: openWater });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene day" }), {
      target: { value: "0.75" },
    });

    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBe(0.75);
    expect(screen.getByRole("slider", { name: "Scene day" })).toHaveValue("0.75");
  });
});
