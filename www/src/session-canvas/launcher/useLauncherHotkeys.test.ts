import { fireEvent, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLauncherHotkeys } from "./useLauncherHotkeys";

function mount(isOpen = false) {
  const toggleRoot = vi.fn();
  const openAgents = vi.fn();
  renderHook(() => useLauncherHotkeys({ toggleRoot, openAgents, isOpen: () => isOpen }));
  return { toggleRoot, openAgents };
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

  it("⌘A opens Agents when closed and focus is not in an editable surface", () => {
    const { openAgents } = mount(false);
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(openAgents).toHaveBeenCalledTimes(1);
  });

  it("⌘A yields to native Select-All when an input is focused (palette closed)", () => {
    const { openAgents } = mount(false);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: "a", metaKey: true });
    expect(openAgents).not.toHaveBeenCalled();
  });

  it("⌘K still toggles even from inside an input", () => {
    const { toggleRoot } = mount(false);
    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: "k", metaKey: true });
    expect(toggleRoot).toHaveBeenCalledTimes(1);
  });

  it("⌘A does not open Agents when the palette is already open", () => {
    const { openAgents } = mount(true);
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(openAgents).not.toHaveBeenCalled();
  });
});
