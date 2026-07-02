import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import * as ts from "typescript";

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);
const RESOLVABLE_SOURCE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx"] as const;
const sourceFileCache = new Map<string, ts.SourceFile>();
const importSpecifiersCache = new Map<string, ImportSpecifier[]>();

export interface ImportSpecifier {
  line: number;
  specifier: string;
}

export function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true })
    .flatMap((entry) => {
      const fullPath = path.join(root, entry.name);
      if (entry.isDirectory()) return sourceFiles(fullPath);
      return entry.isFile() && SOURCE_EXTENSIONS.has(path.extname(fullPath)) ? [fullPath] : [];
    })
    .sort();
}

export function sourceFile(file: string): ts.SourceFile {
  const cached = sourceFileCache.get(file);
  if (cached) return cached;
  const scriptKind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const parsed = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
  sourceFileCache.set(file, parsed);
  return parsed;
}

export function importSpecifiers(file: string): ImportSpecifier[] {
  const cached = importSpecifiersCache.get(file);
  if (cached) return cached;
  const parsed = sourceFile(file);
  const imports: ImportSpecifier[] = [];
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
  importSpecifiersCache.set(file, imports);
  return imports;
}

export function exportedNames(parsed: ts.SourceFile): string[] {
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

export function isInside(candidate: string, root: string): boolean {
  const relativePath = path.relative(root, candidate);
  return relativePath === "" || (!relativePath.startsWith("..") && !path.isAbsolute(relativePath));
}

export function relativeTo(root: string, file: string): string {
  return path.relative(root, file).split(path.sep).join("/");
}

export function isTestSupportSource(file: string): boolean {
  const normalized = file.split(path.sep).join("/");
  return (
    /(^|\/)testSupport\//u.test(normalized) ||
    /(^|\/)testUtils\.tsx?$/u.test(normalized) ||
    /\.(test|testSupport)\.tsx?$/u.test(normalized)
  );
}

export function resolveLocalSpecifier(
  file: string,
  specifier: string,
  srcRoot: string,
): string | null {
  const candidate = localSpecifierCandidate(file, specifier, srcRoot);
  if (candidate === null) return null;
  const resolved = resolveSourceCandidate(candidate);
  if (resolved !== null) return resolved;
  throw new Error(
    `Unresolvable local import ${JSON.stringify(specifier)} from ${relativeTo(srcRoot, file)}`,
  );
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

function localSpecifierCandidate(file: string, specifier: string, srcRoot: string): string | null {
  if (specifier.startsWith(".")) return path.resolve(path.dirname(file), specifier);
  if (specifier.startsWith("@/")) return path.resolve(srcRoot, specifier.slice(2));
  if (specifier.startsWith("@tm/")) return workspacePackageCandidate(specifier, srcRoot);
  if (specifier.startsWith("components/") || specifier.startsWith("session-canvas/")) {
    return path.resolve(srcRoot, specifier);
  }
  return null;
}

/**
 * Resolve `@tm/<pkg>[/<subpath>]` through the package's `exports` map, the
 * same contract the bundler enforces. Unknown packages, packages without an
 * exports map, and subpaths the map does not declare all resolve to a
 * nonexistent candidate, so `resolveLocalSpecifier` keeps failing closed on
 * them: an on-disk file that is not exported is still a forbidden reach-in.
 */
function workspacePackageCandidate(specifier: string, srcRoot: string): string {
  const [, name = "", ...rest] = specifier.split("/");
  const packageRoot = path.resolve(srcRoot, "../..", name);
  const subpath = rest.length === 0 ? "." : `./${rest.join("/")}`;
  const exportsMap = packageExportsMap(packageRoot);
  const target = exportsMap === null ? null : exportedTarget(exportsMap, subpath);
  if (target === null) return path.join(packageRoot, "__unexported__");
  return path.resolve(packageRoot, target);
}

const packageExportsCache = new Map<string, Record<string, unknown> | null>();

function packageExportsMap(packageRoot: string): Record<string, unknown> | null {
  const cached = packageExportsCache.get(packageRoot);
  if (cached !== undefined) return cached;
  let exportsMap: Record<string, unknown> | null = null;
  try {
    const manifest = JSON.parse(readFileSync(path.join(packageRoot, "package.json"), "utf8")) as {
      exports?: Record<string, unknown>;
    };
    exportsMap = manifest.exports ?? null;
  } catch {
    exportsMap = null;
  }
  packageExportsCache.set(packageRoot, exportsMap);
  return exportsMap;
}

function exportedTarget(exportsMap: Record<string, unknown>, subpath: string): string | null {
  const exact = exportsMap[subpath];
  if (typeof exact === "string") return exact;
  for (const [pattern, value] of Object.entries(exportsMap)) {
    if (typeof value !== "string") continue;
    const star = pattern.indexOf("*");
    if (star === -1) continue;
    const prefix = pattern.slice(0, star);
    const suffix = pattern.slice(star + 1);
    if (subpath.length <= prefix.length + suffix.length) continue;
    if (!subpath.startsWith(prefix) || !subpath.endsWith(suffix)) continue;
    return value.replace("*", subpath.slice(prefix.length, subpath.length - suffix.length));
  }
  return null;
}

function resolveSourceCandidate(candidate: string): string | null {
  const candidates = [
    candidate,
    ...RESOLVABLE_SOURCE_EXTENSIONS.map((extension) => `${candidate}${extension}`),
    ...RESOLVABLE_SOURCE_EXTENSIONS.map((extension) => path.join(candidate, `index${extension}`)),
  ];
  return candidates.find(isFile) ?? null;
}

function isFile(candidate: string): boolean {
  try {
    return statSync(candidate).isFile();
  } catch {
    return false;
  }
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
