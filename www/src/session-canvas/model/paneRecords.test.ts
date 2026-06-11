import { describe, expect, it } from "vitest";
import { paneIdForRef, titleForRef } from "../viewers/registry";
import { isCanvasPaneRef, isPaneContentRef } from "./paneRecords";

describe("locator resource refs", () => {
  const pathRef = {
    kind: "resource",
    owner: "local",
    source: "path",
    path: "/tmp/shot.png",
  } as const;
  const urlRef = {
    kind: "resource",
    owner: "local",
    source: "url",
    url: "https://x.test/a/cat.png",
  } as const;

  it("guards accept path and url sources", () => {
    expect(isPaneContentRef(pathRef)).toBe(true);
    expect(isPaneContentRef(urlRef)).toBe(true);
    expect(isCanvasPaneRef(pathRef)).toBe(true);
  });

  it("guards reject malformed locator refs", () => {
    expect(isPaneContentRef({ kind: "resource", owner: "local", source: "path" })).toBe(false);
    expect(isPaneContentRef({ kind: "resource", owner: "local", source: "url", url: 7 })).toBe(
      false,
    );
  });

  it("db refs still validate", () => {
    expect(
      isPaneContentRef({
        kind: "resource",
        owner: "local",
        sessionId: "s",
        resourceId: "r",
      }),
    ).toBe(true);
  });

  it("locator refs survive the persistence JSON round trip and guard", () => {
    expect(isCanvasPaneRef(JSON.parse(JSON.stringify(pathRef)))).toBe(true);
    expect(isCanvasPaneRef(JSON.parse(JSON.stringify(urlRef)))).toBe(true);
  });

  it("pane identity is the locator string", () => {
    expect(paneIdForRef(pathRef)).toBe("resource:path:/tmp/shot.png");
    expect(paneIdForRef(urlRef)).toBe("resource:url:https://x.test/a/cat.png");
  });

  it("titles are the basename or url tail", () => {
    expect(titleForRef(pathRef)).toBe("shot.png");
    expect(titleForRef(urlRef)).toBe("cat.png");
  });
});
