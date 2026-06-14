import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as ts from "typescript";
import { describe, expect, it } from "vitest";

const SESSION_CANVAS_ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = path.resolve(SESSION_CANVAS_ROOT, "..");
const LAB_ROOT = path.join(SESSION_CANVAS_ROOT, "lab");
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);
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

function sourceFiles(root: string): string[] {
  return readdirSync(root)
    .flatMap((entry) => {
      const fullPath = path.join(root, entry);
      const stats = statSync(fullPath);
      if (stats.isDirectory()) return sourceFiles(fullPath);
      return SOURCE_EXTENSIONS.has(path.extname(fullPath)) ? [fullPath] : [];
    })
    .sort();
}

function sourceFile(file: string): ts.SourceFile {
  const scriptKind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
}

function importSpecifiers(file: string): Array<{ line: number; specifier: string }> {
  const parsed = sourceFile(file);
  const imports: Array<{ line: number; specifier: string }> = [];
  const add = (specifier: ts.Node | undefined, lineNode: ts.Node): void => {
    const text = stringLiteralText(specifier);
    if (text === null) return;
    const { line } = parsed.getLineAndCharacterOfPosition(lineNode.getStart(parsed));
    imports.push({ line: line + 1, specifier: text });
  };
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node)) {
      add(node.moduleSpecifier, node);
    } else if (ts.isExportDeclaration(node)) {
      add(node.moduleSpecifier, node);
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      add(node.arguments[0], node);
    } else if (ts.isImportTypeNode(node)) {
      add(importTypeSpecifier(node), node);
    }
    ts.forEachChild(node, visit);
  };
  visit(parsed);
  return imports;
}

function importTypeSpecifier(node: ts.ImportTypeNode): ts.Node | undefined {
  const argument = node.argument;
  if (!ts.isLiteralTypeNode(argument)) return undefined;
  return argument.literal;
}

function stringLiteralText(node: ts.Node | undefined): string | null {
  if (node === undefined) return null;
  return ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : null;
}

function targetsLab(file: string, specifier: string): boolean {
  if (specifier.startsWith(".")) {
    return isInside(path.resolve(path.dirname(file), specifier), LAB_ROOT);
  }
  if (specifier.startsWith("@/")) {
    return isInside(path.resolve(SRC_ROOT, specifier.slice(2)), LAB_ROOT);
  }
  return specifier === "session-canvas/lab" || specifier.startsWith("session-canvas/lab/");
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

function exportedNames(parsed: ts.SourceFile): string[] {
  return parsed.statements.flatMap((statement) => {
    if (ts.isExportDeclaration(statement)) return exportDeclarationNames(statement);
    if (!hasExportModifier(statement)) return [];
    if (ts.isVariableStatement(statement)) {
      return statement.declarationList.declarations.flatMap((declaration) =>
        ts.isIdentifier(declaration.name) ? [declaration.name.text] : [],
      );
    }
    if (
      ts.isFunctionDeclaration(statement) ||
      ts.isClassDeclaration(statement) ||
      ts.isInterfaceDeclaration(statement) ||
      ts.isTypeAliasDeclaration(statement) ||
      ts.isEnumDeclaration(statement)
    ) {
      return statement.name ? [statement.name.text] : [];
    }
    return [];
  });
}

function exportDeclarationNames(statement: ts.ExportDeclaration): string[] {
  const clause = statement.exportClause;
  if (clause === undefined) return [];
  if (ts.isNamedExports(clause)) return clause.elements.map((element) => element.name.text);
  return [clause.name.text];
}

function hasExportModifier(node: ts.Node): boolean {
  const modifiers = ts.canHaveModifiers(node) ? ts.getModifiers(node) : undefined;
  return modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) ?? false;
}

function isInside(candidate: string, root: string): boolean {
  const relativePath = path.relative(root, candidate);
  return relativePath === "" || (!relativePath.startsWith("..") && !path.isAbsolute(relativePath));
}

function relative(file: string): string {
  return path.relative(SRC_ROOT, file).split(path.sep).join("/");
}
