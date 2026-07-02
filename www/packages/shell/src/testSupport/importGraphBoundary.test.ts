import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  importSpecifiers,
  isInside,
  relativeTo,
  resolveLocalSpecifier,
  sourceFiles,
} from "./importGraph";

const PACKAGES_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const INSPECTOR_SRC = path.join(PACKAGES_ROOT, "inspector", "src");
const CANVAS_SRC = path.join(PACKAGES_ROOT, "canvas", "src");

describe("inspector-canvas import graph boundary", () => {
  it("enforces zero inspector to canvas imports", () => {
    expect(crossProductViolations(INSPECTOR_SRC, CANVAS_SRC)).toEqual([]);
  });

  it("enforces zero canvas to inspector imports", () => {
    expect(crossProductViolations(CANVAS_SRC, INSPECTOR_SRC)).toEqual([]);
  });

  it("fails closed for unresolved local aliases", () => {
    expect(() =>
      resolveLocalSpecifier(
        path.join(CANVAS_SRC, "session-canvas", "viewers", "FuturePane.tsx"),
        "@tm/components/FutureInspector",
        CANVAS_SRC,
      ),
    ).toThrow(/Unresolvable local import/u);
  });

  it("fails closed for deep package imports outside the exports map", () => {
    // These files exist on disk, but no exports map declares them. Reaching
    // them must throw, not resolve — a reach-in is a forbidden import even
    // when the file is real.
    for (const specifier of [
      "@tm/core/transport",
      "@tm/core/src/transport",
      "@tm/shell",
      "@tm/inspector/src/app",
      "@tm/inspector/stores/persistence",
      "@tm/canvas/src/index",
      "@tm/canvas/session-canvas/testUtils",
    ]) {
      expect(() =>
        resolveLocalSpecifier(
          path.join(CANVAS_SRC, "session-canvas", "viewers", "FuturePane.tsx"),
          specifier,
          CANVAS_SRC,
        ),
      ).toThrow(/Unresolvable local import/u);
    }
  });

  it("resolves the entrypoints the exports maps declare", () => {
    for (const specifier of [
      "@tm/core",
      "@tm/core/keybindings",
      "@tm/core/testing",
      "@tm/core/types/ir",
      "@tm/host",
      "@tm/inspector",
      "@tm/inspector/inspector.css",
      "@tm/canvas",
      "@tm/canvas/index.css",
      "@tm/canvas/ambient/createAmbientBackground",
    ]) {
      expect(
        resolveLocalSpecifier(
          path.join(CANVAS_SRC, "session-canvas", "viewers", "FuturePane.tsx"),
          specifier,
          CANVAS_SRC,
        ),
      ).not.toBeNull();
    }
  });
});

function crossProductViolations(fromSrc: string, forbiddenSrc: string): string[] {
  return sourceFiles(fromSrc).flatMap((file) =>
    importSpecifiers(file)
      .map(({ specifier }) => {
        const target = resolveLocalSpecifier(file, specifier, fromSrc);
        if (target === null) return null;
        if (!isInside(target, forbiddenSrc)) return null;
        return `${relativeTo(PACKAGES_ROOT, file)} -> ${relativeTo(PACKAGES_ROOT, target)}`;
      })
      .filter((violation): violation is string => violation !== null),
  );
}
