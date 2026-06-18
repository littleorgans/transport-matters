import { isEditableTarget } from "../lib/domFocus";

export type CanvasGestureModifier = "Shift" | "Space";

export interface CanvasGestureSnapshot {
  modifier: CanvasGestureModifier;
  modifierHeld: boolean;
}

type CanvasGestureListener = () => void;
type CanvasGestureEvent = {
  shiftKey?: boolean;
};

export const DEFAULT_CANVAS_GESTURE_MODIFIER: CanvasGestureModifier = "Shift";

let snapshot: CanvasGestureSnapshot = {
  modifier: DEFAULT_CANVAS_GESTURE_MODIFIER,
  modifierHeld: false,
};
let listenersInstalled = false;

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
  updateSnapshot({ modifier, modifierHeld: false });
}

export function shouldPanNotDrag(event?: CanvasGestureEvent | null): boolean {
  ensureCanvasGestureListeners();
  if (snapshot.modifier === "Shift") return Boolean(event?.shiftKey) || snapshot.modifierHeld;
  return snapshot.modifierHeld;
}

export function resetCanvasGestureStoreForTests(): void {
  ensureCanvasGestureListeners();
  updateSnapshot({
    modifier: DEFAULT_CANVAS_GESTURE_MODIFIER,
    modifierHeld: false,
  });
}

function ensureCanvasGestureListeners(): void {
  if (listenersInstalled || typeof document === "undefined" || typeof window === "undefined") {
    return;
  }
  document.addEventListener("keydown", handleKeyDown);
  document.addEventListener("keyup", handleKeyUp);
  window.addEventListener("blur", handleBlur);
  listenersInstalled = true;
}

function handleKeyDown(event: KeyboardEvent): void {
  if (snapshot.modifier === "Shift") {
    if (event.key === "Shift" || event.shiftKey) setModifierHeld(true);
    return;
  }
  if (isEditableTarget(event.target)) return;
  if (isSpaceKeyEvent(event)) setModifierHeld(true);
}

function handleKeyUp(event: KeyboardEvent): void {
  if (snapshot.modifier === "Shift") {
    if (event.key === "Shift" || !event.shiftKey) setModifierHeld(false);
    return;
  }
  if (isSpaceKeyEvent(event)) setModifierHeld(false);
}

function handleBlur(): void {
  setModifierHeld(false);
}

function isSpaceKeyEvent(event: KeyboardEvent): boolean {
  return event.key === " " || event.key === "Spacebar" || event.code === "Space";
}

function setModifierHeld(modifierHeld: boolean): void {
  updateSnapshot({ ...snapshot, modifierHeld });
}

function updateSnapshot(next: CanvasGestureSnapshot): void {
  if (snapshot.modifier === next.modifier && snapshot.modifierHeld === next.modifierHeld) return;
  snapshot = next;
  for (const listener of listeners) listener();
}
