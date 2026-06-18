import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getCanvasGestureSnapshot,
  resetCanvasGestureStoreForTests,
  setCanvasGestureModifier,
  shouldPanNotDrag,
  subscribeCanvasGestureStore,
} from "./gestures";

function modifierKeyDown(key: "Shift" | "Space", target: Document | Element = document): void {
  target.dispatchEvent(keyboardEvent("keydown", key));
}

function modifierKeyUp(key: "Shift" | "Space", target: Document | Element = document): void {
  target.dispatchEvent(keyboardEvent("keyup", key));
}

function keyboardEvent(type: "keydown" | "keyup", key: "Shift" | "Space"): KeyboardEvent {
  return new KeyboardEvent(type, {
    bubbles: true,
    code: key === "Space" ? "Space" : "ShiftLeft",
    key: key === "Space" ? " " : "Shift",
  });
}

describe("canvas gesture store", () => {
  afterEach(() => {
    resetCanvasGestureStoreForTests();
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("tracks the default Shift modifier on keydown and keyup", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCanvasGestureStore(listener);

    modifierKeyDown("Shift");

    expect(getCanvasGestureSnapshot()).toMatchObject({
      modifier: "Shift",
      modifierHeld: true,
    });
    expect(listener).toHaveBeenCalledTimes(1);

    modifierKeyUp("Shift");

    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("clears the held modifier on window blur", () => {
    modifierKeyDown("Shift");

    window.dispatchEvent(new Event("blur"));

    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
  });

  it("keeps Shift held while a chorded key releases", () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { bubbles: true, key: "a", shiftKey: true }),
    );
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(true);

    document.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "a", shiftKey: true }));
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(true);

    modifierKeyUp("Shift");
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
  });

  it("uses Space when configured and ignores Shift", () => {
    setCanvasGestureModifier("Space");

    modifierKeyDown("Shift");
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
    expect(shouldPanNotDrag({ shiftKey: true })).toBe(false);

    modifierKeyDown("Space");
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(true);
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(true);

    modifierKeyUp("Space");
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(false);
  });

  it("keeps editable Space typing from activating canvas gestures", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    setCanvasGestureModifier("Space");

    modifierKeyDown("Space", input);

    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
  });

  it("uses Shift events and held state for the shared pan-not-drag predicate", () => {
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(false);
    expect(shouldPanNotDrag({ shiftKey: true })).toBe(true);

    modifierKeyDown("Shift");

    expect(shouldPanNotDrag({ shiftKey: false })).toBe(true);
  });
});
