/**
 * Canvas is Tailwind-free — a locked decision the spec verified by manual
 * sweep, operationalized here after P6 shipped three stray utilities
 * ("absolute outline-none", "h-full", "sr-only") in the engine and picker.
 * On the shared origin the inspector's Tailwind pass generated utility
 * classes globally, so strays WORKED in dev and silently died in the
 * standalone canvas bundle (panes stacked in static flow; content stopped
 * filling panes). This scans every className string literal in canvas
 * source for utility tokens; canvas classes are BEM (product-prefixed,
 * never bare utility words).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { sourceFiles } from "./importGraph";

const CANVAS_SRC = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
  "canvas",
  "src",
);

// Exact Tailwind utility tokens (the escaped kind: single words a BEM
// codebase never uses bare) plus the value-suffixed families.
const EXACT_UTILITIES = new Set([
  "absolute",
  "relative",
  "fixed",
  "sticky",
  "static",
  "flex",
  "grid",
  "block",
  "inline",
  "hidden",
  "sr-only",
  "outline-none",
  "truncate",
  "uppercase",
  "grow",
  "shrink",
]);
const UTILITY_PATTERN =
  /^-?(?:[mp][trblxyse]?-|w-|h-|min-w-|min-h-|max-w-|max-h-|inset-|top-|bottom-|left-|right-|z-|gap-|space-|text-|bg-|border-|rounded-?|shadow-?|opacity-|flex-|grid-|items-|justify-|self-|col-|row-|overflow-|font-|leading-|tracking-|whitespace-|pointer-events-|select-|cursor-|transition-?|duration-|ease-|scale-|rotate-|translate-|origin-)/u;

const CLASS_NAME_LITERAL = /className\s*=\s*"([^"]*)"/gu;

function utilityViolations(file: string): string[] {
  const content = readFileSync(file, "utf8");
  const violations: string[] = [];
  for (const match of content.matchAll(CLASS_NAME_LITERAL)) {
    for (const token of (match[1] ?? "").split(/\s+/u).filter(Boolean)) {
      if (EXACT_UTILITIES.has(token) || UTILITY_PATTERN.test(token)) {
        violations.push(`${path.relative(CANVAS_SRC, file)}: "${token}"`);
      }
    }
  }
  return violations;
}

describe("canvas Tailwind-free gate", () => {
  it("no className in canvas source carries a Tailwind utility token", () => {
    const violations = sourceFiles(CANVAS_SRC).flatMap(utilityViolations);
    expect(violations).toEqual([]);
  });

  it("fails closed on the utilities the P6 split shipped", () => {
    expect(EXACT_UTILITIES.has("absolute")).toBe(true);
    expect(EXACT_UTILITIES.has("sr-only")).toBe(true);
    expect(UTILITY_PATTERN.test("h-full")).toBe(true);
  });
});
