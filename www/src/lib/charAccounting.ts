import type { ContentBlock, InternalRequest, ToolDef } from "../types";

export interface CharBreakdown {
  system: number;
  tools: number;
  messages: number;
  total: number;
}

type JsonRecord = Record<string, unknown>;

const MAX_DECIMAL_INTEGER_FLOAT = 1e21;
const EXPONENT_PATTERN = /e([+-]?)(0*)(\d+)$/;

function codePointLength(value: string): number {
  return Array.from(value).length;
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const leftCodePoint = leftPoints[index]?.codePointAt(0) ?? 0;
    const rightCodePoint = rightPoints[index]?.codePointAt(0) ?? 0;
    if (leftCodePoint !== rightCodePoint) return leftCodePoint - rightCodePoint;
  }
  return leftPoints.length - rightPoints.length;
}

function normalizeExponent(value: string): string {
  return value
    .toLowerCase()
    .replace(EXPONENT_PATTERN, (_match, sign: string, _zeros: string, digits: string) => {
      const normalizedSign = sign === "-" ? "-" : "";
      return `e${normalizedSign}${Number(digits)}`;
    });
}

function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) {
    throw new Error("non-finite numbers are not valid char-accounting JSON");
  }
  if (Number.isInteger(value) && Math.abs(value) < MAX_DECIMAL_INTEGER_FLOAT) {
    return Math.trunc(value).toString();
  }
  const json = JSON.stringify(value);
  if (json === undefined) {
    throw new Error("unsupported char-accounting JSON number");
  }
  return normalizeExponent(json);
}

function canonicalString(value: string): string {
  const json = JSON.stringify(value);
  if (json === undefined) {
    throw new Error("unsupported char-accounting JSON string");
  }
  return json;
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return canonicalString(value);
  if (typeof value === "number") return canonicalNumber(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (isRecord(value)) {
    const fields = Object.keys(value)
      .sort(compareCodePoints)
      .map((key) => {
        const fieldValue = value[key];
        if (fieldValue === undefined) {
          throw new Error("undefined is not valid char-accounting JSON");
        }
        return `${canonicalString(key)}:${canonicalJson(fieldValue)}`;
      });
    return `{${fields.join(",")}}`;
  }
  throw new Error(`unsupported char-accounting JSON value: ${typeof value}`);
}

function canonicalFields(fields: Array<[string, string]>): string {
  return `{${fields.map(([key, value]) => `${canonicalString(key)}:${value}`).join(",")}}`;
}

function providerData(block: ContentBlock): string {
  return canonicalJson((block as ContentBlock & { provider_data?: unknown }).provider_data ?? null);
}

export function canonicalBlockJson(block: ContentBlock): string {
  switch (block.type) {
    case "text":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["text", canonicalString(block.text)],
        ["provider_data", providerData(block)],
      ]);
    case "tool_use":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["id", canonicalString(block.id)],
        ["name", canonicalString(block.name)],
        ["input", canonicalJson(block.input)],
        ["provider_data", providerData(block)],
      ]);
    case "tool_result":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["tool_use_id", canonicalString(block.tool_use_id)],
        [
          "content",
          `[${(block.content as ContentBlock[]).map((item) => canonicalBlockJson(item)).join(",")}]`,
        ],
        ["is_error", canonicalJson(block.is_error)],
        ["provider_data", providerData(block)],
      ]);
    case "thinking":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["text", canonicalString(block.text)],
        ["provider_data", providerData(block)],
      ]);
    case "image":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["source", canonicalJson(block.source)],
        ["provider_data", providerData(block)],
      ]);
    case "unknown":
      return canonicalFields([
        ["type", canonicalString(block.type)],
        ["raw", canonicalJson(block.raw)],
      ]);
  }
}

export function blockChars(block: ContentBlock): number {
  return codePointLength(canonicalBlockJson(block));
}

export function toolChars(tool: ToolDef, description = tool.description): number {
  return (
    codePointLength(tool.name) +
    codePointLength(description) +
    codePointLength(canonicalJson(tool.input_schema))
  );
}

export function countCharsParts(ir: InternalRequest): CharBreakdown {
  const system = ir.system.reduce((sum, part) => sum + codePointLength(part.text), 0);
  const tools = ir.tools.reduce((sum, tool) => sum + toolChars(tool), 0);
  let messages = 0;
  for (const message of ir.messages) {
    for (const block of message.content) {
      messages += blockChars(block);
    }
  }
  return { system, tools, messages, total: system + tools + messages };
}
