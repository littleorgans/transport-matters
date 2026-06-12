import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createAmbientBackground } from "../../ambient/createAmbientBackground";
import { sceneRegistry } from "../../ambient/sceneRegistry";
import type { AmbientBackground } from "../../ambient/types";
import { useThemeStore } from "../../stores/themeStore";
import { presetTheme } from "../../theme/presets";
import { AmbientBackdrop, driveAmbientScene } from "./AmbientBackdrop";

vi.mock("../../ambient/createAmbientBackground", () => ({
  createAmbientBackground: vi.fn(() => null),
}));

function fakeBackground(): AmbientBackground {
  return {
    setViewport: vi.fn(),
    setSignal: vi.fn(),
    setScene: vi.fn(),
    setReducedMotion: vi.fn(),
    setParam: vi.fn(),
    setPhoto: vi.fn(),
    resize: vi.fn(),
    start: vi.fn(),
    destroy: vi.fn(),
  } as unknown as AmbientBackground;
}

const openWater = presetTheme("open-water");
if (!openWater) throw new Error("expected bundled preset");

beforeEach(() => {
  useThemeStore.setState({ theme: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("driveAmbientScene", () => {
  it("keys every scene param by id and fills defaults the theme omits", () => {
    const bg = fakeBackground();
    driveAmbientScene(bg, openWater.settings);

    expect(bg.setScene).toHaveBeenCalledWith("reference-sea-ii");
    const params = sceneRegistry.paramsFor("reference-sea-ii");
    expect(params.length).toBeGreaterThan(0);
    for (const param of params) {
      expect(bg.setParam).toHaveBeenCalledWith(param.id, param.defaultValue);
    }
  });

  it("pushes a theme override over the scene default", () => {
    const bg = fakeBackground();
    const params = sceneRegistry.paramsFor("reference-sea-ii");
    const first = params[0];
    if (!first) throw new Error("expected scene params");
    driveAmbientScene(bg, {
      ...openWater.settings,
      sceneParams: { [first.id]: first.max },
    });

    expect(bg.setParam).toHaveBeenCalledWith(first.id, first.max);
  });

  it("only sends a photo to scenes that use one", () => {
    const bg = fakeBackground();
    driveAmbientScene(bg, openWater.settings);
    const usesPhoto = sceneRegistry.metadataFor("reference-sea-ii")?.usesPhoto ?? false;
    if (usesPhoto) {
      expect(bg.setPhoto).toHaveBeenCalled();
    } else {
      expect(bg.setPhoto).not.toHaveBeenCalled();
    }
  });
});

describe("AmbientBackdrop", () => {
  it("renders nothing while unthemed", () => {
    const { container } = render(<AmbientBackdrop />);
    expect(container.querySelector(".canvas-ambient-backdrop")).toBeNull();
  });

  it("mounts the scene canvas for a themed session and survives missing WebGL", () => {
    useThemeStore.setState({ theme: openWater });
    const { container } = render(<AmbientBackdrop />);
    // With no engine (jsdom has no WebGL, the mock mirrors that) the CSS
    // gradient stays the background. The canvas element must still mount
    // without crashing so real browsers get the scene.
    expect(container.querySelector(".canvas-ambient-backdrop")).not.toBeNull();
  });

  it("live-applies a param scrub without re-sending the scene", () => {
    // jsdom implements neither WebGL nor matchMedia; with a real (fake) engine
    // the mount effect reaches the reduced-motion media query, so stub it.
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    const bg = fakeBackground();
    vi.mocked(createAmbientBackground).mockReturnValueOnce(bg);
    useThemeStore.setState({ theme: openWater });
    render(<AmbientBackdrop />);

    expect(bg.setScene).toHaveBeenCalledTimes(1);
    vi.mocked(bg.setScene).mockClear();
    vi.mocked(bg.setParam).mockClear();
    vi.mocked(bg.setPhoto).mockClear();

    act(() => {
      useThemeStore.getState().setSceneParam("dayProgress", 0.9);
    });

    expect(bg.setParam).toHaveBeenCalledWith("dayProgress", 0.9);
    expect(bg.setScene).not.toHaveBeenCalled();
    expect(bg.setPhoto).not.toHaveBeenCalled();
  });
});
