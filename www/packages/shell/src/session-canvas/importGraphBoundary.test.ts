import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  importSpecifiers,
  isInside,
  isTestSupportSource,
  relativeTo,
  resolveLocalSpecifier,
  sourceFiles,
} from "../testSupport/importGraph";

const SESSION_CANVAS_ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.resolve(SESSION_CANVAS_ROOT, "..");
const INSPECTOR_COMPONENTS_ROOT = path.join(SRC_ROOT, "components");

describe("session-canvas import graph boundary", () => {
  it("enforces zero canvas to inspector imports", () => {
    const violations = sourceFiles(SESSION_CANVAS_ROOT)
      .filter(isProductionSource)
      .flatMap((file) =>
        importSpecifiers(file)
          .map(({ specifier }) => inspectorImportViolation(file, specifier))
          .filter((violation): violation is string => violation !== null),
      );

    expect(violations).toEqual([]);
  });

  it("fails closed for unresolved local aliases", () => {
    expect(() =>
      resolveLocalSpecifier(
        path.join(SESSION_CANVAS_ROOT, "viewers", "FuturePane.tsx"),
        "@tm/components/FutureInspector",
        SRC_ROOT,
      ),
    ).toThrow(/Unresolvable local import/u);
  });

  it("fails closed for deep package imports outside the exports map", () => {
    // core/src/transport.ts exists on disk, but @tm/core exports only ".",
    // "./keybindings", and "./types/*". Reaching it must throw, not resolve.
    for (const specifier of ["@tm/core/transport", "@tm/core/src/transport", "@tm/shell"]) {
      expect(() =>
        resolveLocalSpecifier(
          path.join(SESSION_CANVAS_ROOT, "viewers", "FuturePane.tsx"),
          specifier,
          SRC_ROOT,
        ),
      ).toThrow(/Unresolvable local import/u);
    }
  });

  it("resolves the entrypoints the exports maps declare", () => {
    for (const specifier of ["@tm/core", "@tm/core/keybindings", "@tm/core/types/ir", "@tm/host"]) {
      expect(
        resolveLocalSpecifier(
          path.join(SESSION_CANVAS_ROOT, "viewers", "FuturePane.tsx"),
          specifier,
          SRC_ROOT,
        ),
      ).not.toBeNull();
    }
  });
});

function isProductionSource(file: string): boolean {
  return !isTestSupportSource(file);
}

function inspectorImportViolation(file: string, specifier: string): string | null {
  const target = resolveLocalSpecifier(file, specifier, SRC_ROOT);
  if (target === null) return null;
  if (!isInside(target, INSPECTOR_COMPONENTS_ROOT)) return null;
  return `${relativeTo(SRC_ROOT, file)} -> ${stripSourceExtension(relativeTo(SRC_ROOT, target))}`;
}

function stripSourceExtension(file: string): string {
  return file.replace(/\.[cm]?[tj]sx?$/u, "");
}
