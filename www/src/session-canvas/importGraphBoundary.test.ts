import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { importSpecifiers, isInside, relativeTo, sourceFiles } from "../testSupport/importGraph";

const SESSION_CANVAS_ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.resolve(SESSION_CANVAS_ROOT, "..");
const INSPECTOR_COMPONENTS_ROOT = path.join(SRC_ROOT, "components");

const KNOWN_CANVAS_TO_INSPECTOR_IMPORTS = [
  "session-canvas/viewers/resource/ProviderExchangeResourceViewer.tsx -> components/ExchangeDetail",
  "session-canvas/viewers/transcript-chat/TranscriptMessage.tsx -> components/detail/ContentBlocks",
];

describe("session-canvas import graph boundary", () => {
  it("pins the current canvas to inspector imports and rejects new ones", () => {
    const violations = sourceFiles(SESSION_CANVAS_ROOT)
      .filter(isProductionSource)
      .flatMap((file) =>
        importSpecifiers(file)
          .map(({ specifier }) => inspectorImportViolation(file, specifier))
          .filter((violation): violation is string => violation !== null),
      );

    expect(violations).toEqual(KNOWN_CANVAS_TO_INSPECTOR_IMPORTS);
  });
});

function isProductionSource(file: string): boolean {
  return !/\.(test|testSupport)\.tsx?$/u.test(file);
}

function inspectorImportViolation(file: string, specifier: string): string | null {
  const target = resolveLocalSpecifier(file, specifier);
  if (target === null) return null;
  if (!isInside(target, INSPECTOR_COMPONENTS_ROOT)) return null;
  return `${relativeTo(SRC_ROOT, file)} -> ${stripSourceExtension(relativeTo(SRC_ROOT, target))}`;
}

function resolveLocalSpecifier(file: string, specifier: string): string | null {
  if (specifier.startsWith(".")) return path.resolve(path.dirname(file), specifier);
  if (specifier.startsWith("@/")) return path.resolve(SRC_ROOT, specifier.slice(2));
  return null;
}

function stripSourceExtension(file: string): string {
  return file.replace(/\.[cm]?[tj]sx?$/u, "");
}
