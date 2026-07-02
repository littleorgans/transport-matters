import { describe, expect, it } from "vitest";
import { selectRootRoute } from "./route";

describe("root route fork", () => {
  it("selects the canvas only for the real canvas path", () => {
    expect(selectRootRoute("/canvas")).toBe("canvas");
    expect(selectRootRoute("/canvas-lab")).toBe("canvas-lab");
    expect(selectRootRoute("/")).toBe("inspector");
    expect(selectRootRoute("/inspector")).toBe("inspector");
  });
});
