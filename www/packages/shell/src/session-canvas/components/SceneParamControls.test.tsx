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

  it("renders the day slider in wall-clock terms: the scene's 0.25 default is noon", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);
    const slider = screen.getByRole("slider", { name: "Scene day" });
    expect(slider).toHaveValue("0.5");
  });

  it("manual scrub stores raw scene units behind the wall-clock display", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene day" }), {
      target: { value: "0.75" }, // wall 18:00
    });

    // stored as scene units (sunset = 0.5), displayed back as wall time
    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBe(0.5);
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

  it("dragging the slider while live drops to manual with a continuous sky", () => {
    useThemeStore.setState({ theme: openWater });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene day" }), {
      target: { value: "0.1" }, // wall 02:24, still night
    });

    expect(useThemeStore.getState().liveDayCycle).toBe(false);
    // stored in scene units: night (0.85), not the scene's dawn at 0.1
    expect(useThemeStore.getState().theme?.settings.sceneParams.dayProgress).toBeCloseTo(0.85);
    expect(screen.getByRole("slider", { name: "Scene day" })).toHaveValue("0.1");
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

  it("surfaces the sun dial for the sea scene, calm by default and with no Live toggle", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);

    expect(screen.getByRole("slider", { name: "Scene sun" })).toHaveValue("0");
    // Only the day param carries a Live toggle; the sun dial is a plain slider.
    expect(screen.getAllByRole("checkbox", { name: "Live" })).toHaveLength(1);
  });

  it("scrubbing the sun dial stores its raw 0..1 value with no clock conversion", () => {
    useThemeStore.setState({ theme: openWater, liveDayCycle: false });
    render(<SceneParamControls />);

    fireEvent.change(screen.getByRole("slider", { name: "Scene sun" }), {
      target: { value: "1" },
    });

    expect(useThemeStore.getState().theme?.settings.sceneParams.sun).toBe(1);
    expect(screen.getByRole("slider", { name: "Scene sun" })).toHaveValue("1");
  });
});
