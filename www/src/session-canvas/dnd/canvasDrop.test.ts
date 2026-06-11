import { describe, expect, it, vi } from "vitest";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import {
  classifyDrop,
  deliverPaneDropToTerminal,
  handleCanvasDrop,
  paneIdAtPoint,
} from "./canvasDrop";

const layout = {
  viewport: { panX: 10, panY: 20, scale: 2 },
  nodes: {
    "terminal:a": {
      paneId: "terminal:a",
      lifecycle: "open",
      rect: { x: 0, y: 0, width: 100, height: 100 },
      z: 1,
    },
    "resource:b": {
      paneId: "resource:b",
      lifecycle: "open",
      rect: { x: 50, y: 50, width: 100, height: 100 },
      z: 2,
    },
  },
} as never;

describe("paneIdAtPoint", () => {
  it("maps screen to world through pan and scale", () => {
    expect(paneIdAtPoint(layout, { x: 30, y: 60 })).toBe("terminal:a");
  });

  it("prefers the highest z when rects overlap", () => {
    expect(paneIdAtPoint(layout, { x: 160, y: 170 })).toBe("resource:b");
  });

  it("returns null on empty canvas space", () => {
    expect(paneIdAtPoint(layout, { x: 9999, y: 9999 })).toBeNull();
  });
});

describe("classifyDrop", () => {
  it("resolves files through the bridge", () => {
    const file = {} as File;
    const transfer = { files: [file], getData: () => "" } as never;
    expect(classifyDrop(transfer, () => "/tmp/shot.png")).toEqual({
      locators: [{ source: "path", locator: "/tmp/shot.png" }],
      unresolvedFiles: false,
    });
  });

  it("flags files without a bridge", () => {
    const transfer = { files: [{} as File], getData: () => "" } as never;
    expect(classifyDrop(transfer, null)).toEqual({ locators: [], unresolvedFiles: true });
  });

  it("flags files the bridge cannot resolve (empty path for non-filesystem drags)", () => {
    const transfer = { files: [{} as File], getData: () => "" } as never;
    expect(classifyDrop(transfer, () => "")).toEqual({ locators: [], unresolvedFiles: true });
  });

  it("keeps resolvable files and drops unresolvable ones from a mixed drag", () => {
    const paths = ["/tmp/shot.png", ""];
    let index = 0;
    const transfer = { files: [{} as File, {} as File], getData: () => "" } as never;
    expect(classifyDrop(transfer, () => paths[index++] ?? "")).toEqual({
      locators: [{ source: "path", locator: "/tmp/shot.png" }],
      unresolvedFiles: false,
    });
  });

  it("parses uri-list drags, skipping comment lines", () => {
    const transfer = {
      files: [],
      getData: (type: string) => (type === "text/uri-list" ? "# c\nhttps://x.test/cat.png\n" : ""),
    } as never;
    expect(classifyDrop(transfer, null)).toEqual({
      locators: [{ source: "url", locator: "https://x.test/cat.png" }],
      unresolvedFiles: false,
    });
  });
});

describe("handleCanvasDrop", () => {
  const baseDeps = () => ({
    resolvePath: () => "/tmp/My Shot.png",
    spawnPane: vi.fn(() => "resource:path:/tmp/My Shot.png"),
    minimizePane: vi.fn(),
    showHint: vi.fn(),
  });

  it("pastes the escaped locator into a terminal target and parks a docked pane", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    const deps = baseDeps();
    handleCanvasDrop(
      layout,
      { x: 30, y: 60 },
      { files: [{} as File], getData: () => "" } as never,
      deps,
    );
    expect(paste).toHaveBeenCalledWith("/tmp/My\\ Shot.png");
    expect(deps.spawnPane).toHaveBeenCalledWith(
      { kind: "resource", owner: "local", source: "path", path: "/tmp/My Shot.png" },
      { focus: false },
    );
    expect(deps.minimizePane).toHaveBeenCalledWith("resource:path:/tmp/My Shot.png");
    unregister();
  });

  it("spawns an open pane on canvas background", () => {
    const deps = baseDeps();
    handleCanvasDrop(
      layout,
      { x: 9999, y: 9999 },
      { files: [{} as File], getData: () => "" } as never,
      deps,
    );
    expect(deps.spawnPane).toHaveBeenCalledWith(
      { kind: "resource", owner: "local", source: "path", path: "/tmp/My Shot.png" },
      undefined,
    );
    expect(deps.minimizePane).not.toHaveBeenCalled();
  });

  it("shows the hint for file drops without a bridge", () => {
    const deps = { ...baseDeps(), resolvePath: null };
    handleCanvasDrop(
      layout,
      { x: 30, y: 60 },
      { files: [{} as File], getData: () => "" } as never,
      deps,
    );
    expect(deps.showHint).toHaveBeenCalledWith(
      "File drops need the desktop app. URL drags work here.",
    );
    expect(deps.spawnPane).not.toHaveBeenCalled();
  });
});

describe("deliverPaneDropToTerminal", () => {
  const rectOver = (x: number, y: number) => ({ x, y, width: 40, height: 40 });
  const pathRef = {
    kind: "resource",
    owner: "local",
    source: "path",
    path: "/tmp/My Shot.png",
  } as const;

  it("pastes the moved locator pane's locator into the terminal under its center", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    deliverPaneDropToTerminal(layout, pathRef, "resource:path:/tmp/My Shot.png", rectOver(10, 10));
    expect(paste).toHaveBeenCalledWith("/tmp/My\\ Shot.png");
    unregister();
  });

  it("does nothing when a non-terminal pane is stacked over a terminal", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    deliverPaneDropToTerminal(layout, pathRef, "resource:path:/tmp/My Shot.png", rectOver(30, 30));
    expect(paste).not.toHaveBeenCalled();
    unregister();
  });

  it("does nothing for non-locator panes", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    deliverPaneDropToTerminal(
      layout,
      { kind: "resource", owner: "local", sessionId: "s", resourceId: "r" },
      "resource:s:r",
      rectOver(30, 30),
    );
    expect(paste).not.toHaveBeenCalled();
    unregister();
  });

  it("never targets the moved pane itself", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    deliverPaneDropToTerminal(layout, pathRef, "terminal:a", rectOver(30, 30));
    expect(paste).not.toHaveBeenCalled();
    unregister();
  });
});
