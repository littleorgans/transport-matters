// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { dragModeForTarget } from "./PaneFrame";

function element(html: string): Element {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host.querySelector("[data-probe]") as Element;
}

describe("dragModeForTarget", () => {
  it("keeps handle behavior regardless of bodyDrag", () => {
    const handle = element(`<div data-pane-drag-handle="true"><span data-probe></span></div>`);
    expect(dragModeForTarget(handle, false)).toBe("move");
    const resize = element(`<div data-pane-resize-handle="true"><span data-probe></span></div>`);
    expect(dragModeForTarget(resize, true)).toBe("resize");
  });

  it("bodyDrag turns plain body targets into move, but never interactive ones", () => {
    const body = element(`<div><img data-probe alt="" /></div>`);
    expect(dragModeForTarget(body, true)).toBe("move");
    expect(dragModeForTarget(body, false)).toBeNull();
    const button = element(`<div><button data-probe type="button"></button></div>`);
    expect(dragModeForTarget(button, true)).toBeNull();
  });
});
