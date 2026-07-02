import {
  type CanvasGestureModifier,
  DEFAULT_CANVAS_GESTURE_MODIFIER,
  isEditableTarget,
  isInteractiveTarget,
} from "@tm/core/keybindings";
import { useKeymapStore } from "../stores/keymapStore";

export { type CanvasGestureModifier, DEFAULT_CANVAS_GESTURE_MODIFIER } from "@tm/core/keybindings";

export interface CanvasGestureSnapshot {
  modifier: CanvasGestureModifier;
  modifierHeld: boolean;
}

type CanvasGestureListener = () => void;
type CanvasGestureEvent = {
  shiftKey?: boolean;
};

export const CANVAS_GESTURE_SURFACE_ATTRIBUTE = "data-canvas-gesture-surface";

const CANVAS_GESTURE_SURFACE_SELECTOR = `[${CANVAS_GESTURE_SURFACE_ATTRIBUTE}='true']`;

let modifierHeld = false;
let snapshot = createSnapshot();
let listenersInstalled = false;
let keymapUnsubscribe: (() => void) | null = null;

const listeners = new Set<CanvasGestureListener>();

export function getCanvasGestureSnapshot(): CanvasGestureSnapshot {
  ensureCanvasGestureListeners();
  return snapshot;
}

export function subscribeCanvasGestureStore(listener: CanvasGestureListener): () => void {
  ensureCanvasGestureListeners();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setCanvasGestureModifier(modifier: CanvasGestureModifier): void {
  ensureCanvasGestureListeners();
  useKeymapStore.getState().setCanvasGestureModifier(modifier);
}

export function shouldPanNotDrag(event?: CanvasGestureEvent | null): boolean {
  ensureCanvasGestureListeners();
  if (getCanvasGestureModifier() === "Shift") return Boolean(event?.shiftKey) || modifierHeld;
  return modifierHeld;
}

export function resetCanvasGestureStoreForTests(): void {
  ensureCanvasGestureListeners();
  useKeymapStore.getState().setCanvasGestureModifier(DEFAULT_CANVAS_GESTURE_MODIFIER);
  setModifierHeld(false);
}

function ensureCanvasGestureListeners(): void {
  if (!keymapUnsubscribe) {
    keymapUnsubscribe = useKeymapStore.subscribe(() => {
      modifierHeld = false;
      updateSnapshot();
    });
    updateSnapshot();
  }
  if (listenersInstalled || typeof document === "undefined" || typeof window === "undefined") {
    return;
  }
  document.addEventListener("keydown", handleKeyDown);
  document.addEventListener("keyup", handleKeyUp);
  window.addEventListener("blur", handleBlur);
  listenersInstalled = true;
}

function handleKeyDown(event: KeyboardEvent): void {
  if (getCanvasGestureModifier() === "Shift") {
    if (event.key === "Shift" || event.shiftKey) setModifierHeld(true);
    return;
  }
  if (!isSpaceKeyEvent(event) || !isCanvasSpaceGestureTarget(event.target)) return;
  event.preventDefault();
  setModifierHeld(true);
}

function handleKeyUp(event: KeyboardEvent): void {
  if (getCanvasGestureModifier() === "Shift") {
    if (event.key === "Shift" || !event.shiftKey) setModifierHeld(false);
    return;
  }
  if (isSpaceKeyEvent(event)) setModifierHeld(false);
}

function handleBlur(): void {
  setModifierHeld(false);
}

function getCanvasGestureModifier(): CanvasGestureModifier {
  return useKeymapStore.getState().canvasGestureModifier;
}

function createSnapshot(): CanvasGestureSnapshot {
  return {
    modifier: getCanvasGestureModifier(),
    modifierHeld,
  };
}

function isSpaceKeyEvent(event: KeyboardEvent): boolean {
  return event.key === " " || event.key === "Spacebar" || event.code === "Space";
}

function isCanvasSpaceGestureTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (isEditableTarget(target) || isInteractiveTarget(target)) return false;
  // Space is a canvas gesture only when focus is on the LayoutCanvas surface.
  // That keeps native Space activation for buttons and ARIA controls.
  return target.matches(CANVAS_GESTURE_SURFACE_SELECTOR);
}

function setModifierHeld(nextModifierHeld: boolean): void {
  if (modifierHeld === nextModifierHeld) return;
  modifierHeld = nextModifierHeld;
  updateSnapshot();
}

function updateSnapshot(): void {
  const next = createSnapshot();
  if (snapshot.modifier === next.modifier && snapshot.modifierHeld === next.modifierHeld) return;
  snapshot = next;
  for (const listener of listeners) listener();
}
