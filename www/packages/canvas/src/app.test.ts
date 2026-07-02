import { describe, expect, it } from "vitest";
import { selectCanvasRoute } from "./app";

describe("selectCanvasRoute", () => {
  it("serves the lab at /canvas-lab", () => {
    expect(selectCanvasRoute("/canvas-lab")).toBe("canvas-lab");
  });

  it("defaults every other canvas-bundle path to the session canvas", () => {
    for (const pathname of ["/canvas", "/canvas/", "/canvas/deep/link"]) {
      expect(selectCanvasRoute(pathname)).toBe("canvas");
    }
  });
});
