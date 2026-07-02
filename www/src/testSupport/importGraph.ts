import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import * as ts from "typescript";

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);

export interface ImportSpecifier {
  line: number;
  specifier: string;
}

export function sourceFiles(root: string): string[] {
  return readdirSync(root)
    .flatMap((entry) => {
      const fullPath = path.join(root, entry);
      const stats = statSync(fullPath);
      if (stats.isDirectory()) return sourceFiles(fullPath);
      return SOURCE_EXTENSIONS.has(path.extname(fullPath)) ? [fullPath] : [];
    })
    .sort();
}

export function sourceFile(file: string): ts.SourceFile {
  const scriptKind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
}

export function importSpecifiers(file: string): ImportSpecifier[] {
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

function importTypeSpecifier(node: ts.ImportTypeNode): ts.Node | undefined {
  const argument = node.argument;
  if (!ts.isLiteralTypeNode(argument)) return undefined;
  return argument.literal;
}

function stringLiteralText(node: ts.Node | undefined): string | null {
  if (node === undefined) return null;
  return ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : null;
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
