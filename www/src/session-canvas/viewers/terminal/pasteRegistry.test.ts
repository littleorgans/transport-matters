import { describe, expect, it } from "vitest";
import { escapeDropLocator, registerPasteHandle, resolvePasteHandle } from "./pasteRegistry";

describe("pasteRegistry", () => {
  it("registers, resolves, and deregisters a handle", () => {
    const paste = (_: string) => {};
    const unregister = registerPasteHandle("terminal:1", paste);
    expect(resolvePasteHandle("terminal:1")).toBe(paste);
    unregister();
    expect(resolvePasteHandle("terminal:1")).toBeNull();
  });

  it("a stale unregister does not evict a newer handle", () => {
    const first = registerPasteHandle("terminal:1", (_) => {});
    const second = (_: string) => {};
    registerPasteHandle("terminal:1", second);
    first();
    expect(resolvePasteHandle("terminal:1")).toBe(second);
  });
});

describe("escapeDropLocator", () => {
  it("backslash-escapes shell-unsafe path characters (iTerm drag convention)", () => {
    expect(escapeDropLocator({ source: "path", locator: "/tmp/My Shot (1).png" })).toBe(
      "/tmp/My\\ Shot\\ \\(1\\).png",
    );
  });

  it("passes urls through unescaped", () => {
    expect(escapeDropLocator({ source: "url", locator: "https://x.test/a b" })).toBe(
      "https://x.test/a b",
    );
  });
});
