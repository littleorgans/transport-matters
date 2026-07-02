import { describe, expect, it, vi } from "vitest";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import {
  classifyDrop,
  handleCanvasDrop,
  handleDockDrop,
  locatorForPaneRef,
  paneIdAtPoint,
} from "./canvasDrop";

const layout = {
  viewport: { panX: 10, panY: 20, scale: 2 },
  order: ["terminal:a", "resource:b"],
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

describe("locatorForPaneRef", () => {
  it("maps resource path and url refs to their locators", () => {
    expect(
      locatorForPaneRef({ kind: "resource", owner: "local", source: "path", path: "/tmp/a.png" }),
    ).toEqual({ source: "path", locator: "/tmp/a.png" });
    expect(
      locatorForPaneRef({
        kind: "resource",
        owner: "local",
        source: "url",
        url: "https://x.test/c.png",
      }),
    ).toEqual({ source: "url", locator: "https://x.test/c.png" });
  });

  it("maps everything else to null, the guard living in the one predicate", () => {
    expect(locatorForPaneRef(null)).toBeNull();
    expect(locatorForPaneRef(undefined)).toBeNull();
    expect(locatorForPaneRef({ kind: "terminal", owner: "local", worktreeId: "wt-1" })).toBeNull();
    expect(
      locatorForPaneRef({ kind: "resource", owner: "local", sessionId: "s", resourceId: "r" }),
    ).toBeNull();
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
    dockPane: vi.fn(),
    showHint: vi.fn(),
  });

  it("pastes the escaped locator into a terminal target and docks the resource directly", () => {
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
    // straight to the dock: never spawn a pane just to minimize it, which
    // resized the layout twice in quick succession
    expect(deps.dockPane).toHaveBeenCalledWith({
      kind: "resource",
      owner: "local",
      source: "path",
      path: "/tmp/My Shot.png",
    });
    expect(deps.spawnPane).not.toHaveBeenCalled();
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
    expect(deps.dockPane).not.toHaveBeenCalled();
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

describe("handleDockDrop", () => {
  const dockDeps = () => ({ dockPane: vi.fn(), restorePaneAtIndex: vi.fn() });
  const locatorPayload = {
    paneId: "resource:path:/tmp/My Shot.png",
    ref: { kind: "resource", owner: "local", source: "path", path: "/tmp/My Shot.png" } as const,
  };

  it("pastes a locator ref into a terminal and bumps the dock entry, no restore", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    const deps = dockDeps();

    handleDockDrop(layout, { x: 30, y: 60 }, locatorPayload, deps);

    expect(paste).toHaveBeenCalledWith("/tmp/My\\ Shot.png");
    // decision 4: a paste is a read, the entry STAYS DOCKED; dockPane de-dupes
    // and bumps it to the dock front, same substrate as external-drop paste
    expect(deps.dockPane).toHaveBeenCalledWith({
      kind: "resource",
      owner: "local",
      source: "path",
      path: "/tmp/My Shot.png",
    });
    expect(deps.restorePaneAtIndex).not.toHaveBeenCalled();
    unregister();
  });

  it("restores a non-locator ref at the target pane's slot even over a paste handle", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("terminal:a", paste);
    const deps = dockDeps();

    // null-ref demo pane: nothing to deliver, so it is not a paste target (decision 3)
    handleDockDrop(layout, { x: 30, y: 60 }, { paneId: "lab-2", ref: null }, deps);

    expect(paste).not.toHaveBeenCalled();
    expect(deps.dockPane).not.toHaveBeenCalled();
    expect(deps.restorePaneAtIndex).toHaveBeenCalledWith("lab-2", 0);
    unregister();
  });

  it("restores at the nearest slot when dropped on canvas background", () => {
    const deps = dockDeps();

    // far corner: no containment, resource:b's center is nearer -> its slot
    handleDockDrop(layout, { x: 9999, y: 9999 }, locatorPayload, deps);

    expect(deps.restorePaneAtIndex).toHaveBeenCalledWith(locatorPayload.paneId, 1);
    expect(deps.dockPane).not.toHaveBeenCalled();
  });

  it("appends when no panes are open", () => {
    const empty = { viewport: { panX: 0, panY: 0, scale: 1 }, order: [], nodes: {} } as never;
    const deps = dockDeps();

    handleDockDrop(empty, { x: 10, y: 10 }, locatorPayload, deps);

    expect(deps.restorePaneAtIndex).toHaveBeenCalledWith(locatorPayload.paneId, 0);
  });
});
