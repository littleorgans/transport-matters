import { cleanup, fireEvent, renderHook } from "@testing-library/react";
import type { KeybindingPlatform } from "@tm/core/keybindings";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeybindingEngineProvider } from "../../keybindings/engine";
import { useLauncherHotkeys } from "./useLauncherHotkeys";

const MAC_PLATFORM: KeybindingPlatform = {
  isMac: true,
  modToken: "Meta",
  rawPlatform: "darwin",
  source: "desktop-bridge",
};

function mount(isOpen = false) {
  const toggleRoot = vi.fn();
  const openScope = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(KeybindingEngineProvider, { platform: MAC_PLATFORM }, children);
  renderHook(() => useLauncherHotkeys({ toggleRoot, openScope, isOpen: () => isOpen }), {
    wrapper,
  });
  return { toggleRoot, openScope };
}

describe("useLauncherHotkeys", () => {
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
  });

  it("$mod+K toggles the root scope", () => {
    const { toggleRoot } = mount(false);
    fireEvent.keyDown(window, { key: "k", code: "KeyK", metaKey: true });
    expect(toggleRoot).toHaveBeenCalledTimes(1);
  });

  it("$mod+A opens the Agents scope when closed and focus is not editable", () => {
    const { openScope } = mount(false);
    fireEvent.keyDown(window, { key: "a", code: "KeyA", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("agents");
  });

  it("$mod+A yields to native Select-All when an input is focused (palette closed)", () => {
    const { openScope } = mount(false);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: "a", code: "KeyA", metaKey: true });
    expect(openScope).not.toHaveBeenCalled();
  });

  it("$mod+A does not open Agents when the palette is already open", () => {
    const { openScope } = mount(true);
    fireEvent.keyDown(window, { key: "a", code: "KeyA", metaKey: true });
    expect(openScope).not.toHaveBeenCalled();
  });

  it("$mod+, jumps to the Settings scope from anywhere (no editable guard)", () => {
    const { openScope } = mount(false);
    fireEvent.keyDown(window, { key: ",", code: "Comma", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("settings");
  });

  it("$mod+, still jumps to Settings while typing in an input", () => {
    const { openScope } = mount(true);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: ",", code: "Comma", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("settings");
  });
});
