import { afterEach, describe, expect, it, vi } from "vitest";
import { CANVAS_STORAGE_KEYS } from "../session-canvas/persistence/storageKeys";
import { useKeymapStore } from "../stores/keymapStore";
import {
  CANVAS_GESTURE_SURFACE_ATTRIBUTE,
  getCanvasGestureSnapshot,
  resetCanvasGestureStoreForTests,
  setCanvasGestureModifier,
  shouldPanNotDrag,
  subscribeCanvasGestureStore,
} from "./gestures";

function modifierKeyDown(
  key: "Shift" | "Space",
  target: Document | Element = document,
): KeyboardEvent {
  const event = keyboardEvent("keydown", key);
  target.dispatchEvent(event);
  return event;
}

function modifierKeyUp(key: "Shift" | "Space", target: Document | Element = document): void {
  target.dispatchEvent(keyboardEvent("keyup", key));
}

function keyboardEvent(type: "keydown" | "keyup", key: "Shift" | "Space"): KeyboardEvent {
  return new KeyboardEvent(type, {
    bubbles: true,
    cancelable: true,
    code: key === "Space" ? "Space" : "ShiftLeft",
    key: key === "Space" ? " " : "Shift",
  });
}

function canvasGestureSurface(): HTMLElement {
  const surface = document.createElement("section");
  surface.setAttribute(CANVAS_GESTURE_SURFACE_ATTRIBUTE, "true");
  document.body.appendChild(surface);
  return surface;
}

describe("canvas gesture store", () => {
  afterEach(() => {
    resetCanvasGestureStoreForTests();
    localStorage.clear();
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
    const surface = canvasGestureSurface();
    setCanvasGestureModifier("Space");

    modifierKeyDown("Shift");
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
    expect(shouldPanNotDrag({ shiftKey: true })).toBe(false);

    modifierKeyDown("Space", surface);
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(true);
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(true);

    modifierKeyUp("Space");
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(false);
  });

  it("uses rehydrated Space and no longer pans with Shift", async () => {
    const surface = canvasGestureSurface();
    useKeymapStore.setState({ canvasGestureModifier: "Shift" });
    localStorage.setItem(
      CANVAS_STORAGE_KEYS.keymapStore,
      JSON.stringify({ state: { canvasGestureModifier: "Space" }, version: 1 }),
    );

    await useKeymapStore.persist.rehydrate();

    modifierKeyDown("Shift");
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
    expect(shouldPanNotDrag({ shiftKey: true })).toBe(false);

    modifierKeyDown("Space", surface);
    expect(getCanvasGestureSnapshot()).toMatchObject({
      modifier: "Space",
      modifierHeld: true,
    });
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(true);
  });

  it("keeps editable Space typing from activating canvas gestures", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    setCanvasGestureModifier("Space");

    modifierKeyDown("Space", input);

    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
  });

  it("prevents Space default only on the canvas gesture surface", () => {
    const surface = canvasGestureSurface();
    setCanvasGestureModifier("Space");

    const event = modifierKeyDown("Space", surface);

    expect(event.defaultPrevented).toBe(true);
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(true);
  });

  it("does not prevent Space or arm gestures on buttons or ARIA controls", () => {
    const button = document.createElement("button");
    button.type = "button";
    const ariaButton = document.createElement("div");
    ariaButton.setAttribute("role", "button");
    document.body.append(button, ariaButton);
    setCanvasGestureModifier("Space");

    const nativeEvent = modifierKeyDown("Space", button);
    expect(nativeEvent.defaultPrevented).toBe(false);
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);

    const ariaEvent = modifierKeyDown("Space", ariaButton);
    expect(ariaEvent.defaultPrevented).toBe(false);
    expect(getCanvasGestureSnapshot().modifierHeld).toBe(false);
  });

  it("uses Shift events and held state for the shared pan-not-drag predicate", () => {
    expect(shouldPanNotDrag({ shiftKey: false })).toBe(false);
    expect(shouldPanNotDrag({ shiftKey: true })).toBe(true);

    modifierKeyDown("Shift");

    expect(shouldPanNotDrag({ shiftKey: false })).toBe(true);
  });
});
