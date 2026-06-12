import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useThemeStore } from "../../stores/themeStore";
import { presetTheme } from "../../theme/presets";
import { SceneParamControls } from "./SceneParamControls";

const openWater = presetTheme("open-water");
const littleorgans = presetTheme("littleorgans");
if (!openWater || !littleorgans) throw new Error("expected bundled presets");

beforeEach(() => {
  useThemeStore.setState({ theme: null, liveDayCycle: true });
});

afterEach(() => {
  vi.useRealTimers();
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

  it("renders the day slider at the scene default in manual mode", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);
    const slider = screen.getByRole("slider", { name: "Scene day" });
    expect(slider).toHaveValue("0.25");
  });

  it("scrubbing in manual mode writes the param through the store", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene day" }), {
      target: { value: "0.75" },
    });

    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBe(0.75);
    expect(screen.getByRole("slider", { name: "Scene day" })).toHaveValue("0.75");
  });

  it("live mode mirrors the local clock on the slider, not the stored baseline", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 13, 18, 0, 0)); // 18:00 -> 0.75
    useThemeStore.setState({ theme: openWater });
    render(<SceneParamControls />);

    expect(screen.getByRole("checkbox", { name: "Live" })).toBeChecked();
    expect(screen.getByRole("slider", { name: "Scene day" })).toHaveValue("0.75");
    expect(openWater.settings.sceneParams.dayProgress).toBeUndefined();
  });

  it("dragging the slider while live drops to manual and keeps the value", () => {
    useThemeStore.setState({ theme: openWater });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene day" }), {
      target: { value: "0.1" },
    });

    expect(useThemeStore.getState().liveDayCycle).toBe(false);
    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBe(0.1);
    expect(screen.getByRole("checkbox", { name: "Live" })).not.toBeChecked();
  });

  it("the live toggle switches modes both ways", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Live" }));
    expect(useThemeStore.getState().liveDayCycle).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Live" }));
    expect(useThemeStore.getState().liveDayCycle).toBe(false);
  });
});
