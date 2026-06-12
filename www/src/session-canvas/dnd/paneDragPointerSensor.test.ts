import { describe, expect, it } from "vitest";
import { shouldStartPaneDrag } from "./paneDragPointerSensor";

interface FrameOptions {
  bodyDrag?: boolean;
}

function paneFixture({ bodyDrag = false }: FrameOptions = {}) {
  const frame = document.createElement("div");
  frame.dataset.paneFrame = "true";
  frame.dataset.paneBodyDrag = bodyDrag ? "true" : "false";

  const header = document.createElement("div");
  header.dataset.paneDragHandle = "true";
  frame.appendChild(header);

  const resizeHandle = document.createElement("div");
  resizeHandle.dataset.paneResizeHandle = "true";
  frame.appendChild(resizeHandle);

  const body = document.createElement("div");
  frame.appendChild(body);

  const bodyButton = document.createElement("button");
  body.appendChild(bodyButton);

  return { frame, header, resizeHandle, body, bodyButton };
}

function pointerDown(target: Element, init: Partial<PointerEventInit> = {}) {
  return {
    isPrimary: true,
    button: 0,
    shiftKey: false,
    target,
    ...init,
  } as unknown as PointerEvent;
}

describe("shouldStartPaneDrag", () => {
  it("starts from the drag handle", () => {
    const { header } = paneFixture();
    expect(shouldStartPaneDrag(pointerDown(header))).toBe(true);
  });

  it("declines Shift+drag: the canvas pan owns it", () => {
    const { header } = paneFixture();
    expect(shouldStartPaneDrag(pointerDown(header, { shiftKey: true }))).toBe(false);
  });

  it("declines secondary buttons and non-primary pointers", () => {
    const { header } = paneFixture();
    expect(shouldStartPaneDrag(pointerDown(header, { button: 2 }))).toBe(false);
    expect(shouldStartPaneDrag(pointerDown(header, { isPrimary: false }))).toBe(false);
  });

  it("declines resize handles: @use-gesture owns resize", () => {
    const { resizeHandle } = paneFixture();
    expect(shouldStartPaneDrag(pointerDown(resizeHandle))).toBe(false);
  });

  it("declines the pane body unless the pane opted into bodyDrag", () => {
    const plain = paneFixture();
    expect(shouldStartPaneDrag(pointerDown(plain.body))).toBe(false);

    const optedIn = paneFixture({ bodyDrag: true });
    expect(shouldStartPaneDrag(pointerDown(optedIn.body))).toBe(true);
  });

  it("declines interactive controls inside a bodyDrag pane", () => {
    const { bodyButton } = paneFixture({ bodyDrag: true });
    expect(shouldStartPaneDrag(pointerDown(bodyButton))).toBe(false);
  });
});
