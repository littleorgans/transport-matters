import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  exportedNames,
  importSpecifiers,
  isInside,
  relativeTo,
  resolveLocalSpecifier,
  sourceFile,
  sourceFiles,
} from "../testSupport/importGraph";

const SESSION_CANVAS_ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.resolve(SESSION_CANVAS_ROOT, "..");
const LAB_ROOT = path.join(SESSION_CANVAS_ROOT, "lab");
const FORBIDDEN_LAB_EXPORTS = new Set([
  "useCapturedRunStore",
  "createCapturedRunKey",
  "capturedRunLifecyclePolicy",
  "registerLifecycle",
]);
const FORBIDDEN_LAB_FILES = new Set([
  "capturedRunStore.ts",
  "capturedRunStore.tsx",
  "labLifecycle.ts",
  "labLifecycle.tsx",
]);

describe("session-canvas lab boundary", () => {
  it("keeps non-lab session-canvas files from importing lab modules", () => {
    const violations = sourceFiles(SESSION_CANVAS_ROOT)
      .filter((file) => !isInside(file, LAB_ROOT))
      .flatMap((file) =>
        importSpecifiers(file)
          .filter(({ specifier }) => targetsLab(file, specifier))
          .map(({ line, specifier }) => `${relative(file)}:${line}: ${specifier}`),
      );

    expect(violations).toEqual([]);
  });

  it("keeps migrated run-pane machinery out of lab exports", () => {
    const violations = sourceFiles(LAB_ROOT).flatMap((file) => labLegacyViolations(file));

    expect(violations).toEqual([]);
  });
});

function targetsLab(file: string, specifier: string): boolean {
  const target = resolveLocalSpecifier(file, specifier, SRC_ROOT);
  return target !== null && isInside(target, LAB_ROOT);
}

function labLegacyViolations(file: string): string[] {
  const parsed = sourceFile(file);
  const text = parsed.getFullText();
  const violations: string[] = [];

  if (FORBIDDEN_LAB_FILES.has(path.basename(file))) {
    violations.push(`${relative(file)}: legacy run-pane module remains`);
  }
  if (/\bregisterLifecycle\s*\(/.test(text) || /\bPaneLifecyclePolicy\b/.test(text)) {
    violations.push(`${relative(file)}: lifecycle registration belongs in core`);
  }

  for (const exportName of exportedNames(parsed)) {
    if (FORBIDDEN_LAB_EXPORTS.has(exportName) || /^createCapturedRun.*Ref$/u.test(exportName)) {
      violations.push(`${relative(file)}: exports ${exportName}`);
    }
  }
  return violations;
}

function relative(file: string): string {
  return relativeTo(SRC_ROOT, file);
}
