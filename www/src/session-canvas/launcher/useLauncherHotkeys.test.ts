import { fireEvent, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLauncherHotkeys } from "./useLauncherHotkeys";

function mount(isOpen = false) {
  const toggleRoot = vi.fn();
  const openScope = vi.fn();
  renderHook(() => useLauncherHotkeys({ toggleRoot, openScope, isOpen: () => isOpen }));
  return { toggleRoot, openScope };
}

describe("useLauncherHotkeys", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("⌘K toggles the root scope", () => {
    const { toggleRoot } = mount(false);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(toggleRoot).toHaveBeenCalledTimes(1);
  });

  it("⌘A opens the Agents scope when closed and focus is not editable", () => {
    const { openScope } = mount(false);
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("agents");
  });

  it("⌘A yields to native Select-All when an input is focused (palette closed)", () => {
    const { openScope } = mount(false);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: "a", metaKey: true });
    expect(openScope).not.toHaveBeenCalled();
  });

  it("⌘A does not open Agents when the palette is already open", () => {
    const { openScope } = mount(true);
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(openScope).not.toHaveBeenCalled();
  });

  it("⌘, jumps to the Settings scope from anywhere (no editable guard)", () => {
    const { openScope } = mount(false);
    fireEvent.keyDown(window, { key: ",", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("settings");
  });

  it("⌘, still jumps to Settings while typing in an input", () => {
    const { openScope } = mount(true);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: ",", metaKey: true });
    expect(openScope).toHaveBeenCalledWith("settings");
  });
});
