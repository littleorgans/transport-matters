import { afterEach, describe, expect, it } from "vitest";
import {
  clearActiveDockDrag,
  PANE_REF_MIME,
  parseDockDragPayload,
  readActiveDockDrag,
  setActiveDockDrag,
} from "./dockDragSource";

const ENTRY = {
  paneId: "resource:1",
  ref: { kind: "resource", owner: "local", source: "path", path: "/tmp/a.png" } as const,
};

describe("dockDragSource", () => {
  afterEach(() => clearActiveDockDrag());

  it("publishes the in-flight entry for the dragover resolver and clears it", () => {
    expect(readActiveDockDrag()).toBeNull();

    setActiveDockDrag(ENTRY);
    expect(readActiveDockDrag()).toEqual(ENTRY);

    clearActiveDockDrag();
    expect(readActiveDockDrag()).toBeNull();
  });

  it("names the pane-ref mime both drag ends key off", () => {
    expect(PANE_REF_MIME).toBe("application/x-tm-pane-ref");
  });

  it("parses the drop-time payload and rejects malformed mimes", () => {
    expect(parseDockDragPayload(JSON.stringify(ENTRY))).toEqual(ENTRY);
    expect(parseDockDragPayload(JSON.stringify({ paneId: "lab-2", ref: null }))).toEqual({
      paneId: "lab-2",
      ref: null,
    });

    // cross-window or hostile payloads must not throw, just resolve to nothing
    expect(parseDockDragPayload("")).toBeNull();
    expect(parseDockDragPayload("not json")).toBeNull();
    expect(parseDockDragPayload('"a string"')).toBeNull();
    expect(parseDockDragPayload(JSON.stringify({ ref: null }))).toBeNull();
  });
});
