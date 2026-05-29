import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { ContentBlock, InternalRequest, ToolDef } from "../types";
import { canonicalBlockJson, canonicalJson, countCharsParts, toolChars } from "./charAccounting";

interface Fixture {
  numbers: unknown;
  tool: ToolDef;
  blocks: Record<string, ContentBlock>;
  internal_request: InternalRequest;
  expected: {
    numbers_json: string;
    tool_input_schema_json: string;
    tool_chars: number;
    blocks: Record<string, string>;
    parts: {
      system: number;
      tools: number;
      messages: number;
      total: number;
    };
  };
}

function loadFixture(): Fixture {
  const body = readFileSync(resolve(process.cwd(), "../shared/char_accounting_v1.json"), "utf8");
  return JSON.parse(body) as Fixture;
}

describe("char accounting", () => {
  it("matches the shared Python fixture contract", () => {
    const fixture = loadFixture();

    expect(canonicalJson(fixture.numbers)).toBe(fixture.expected.numbers_json);
    expect(canonicalJson(fixture.tool.input_schema)).toBe(fixture.expected.tool_input_schema_json);
    expect(toolChars(fixture.tool)).toBe(fixture.expected.tool_chars);

    for (const [name, block] of Object.entries(fixture.blocks)) {
      expect(canonicalBlockJson(block)).toBe(fixture.expected.blocks[name]);
    }

    expect(countCharsParts(fixture.internal_request)).toEqual(fixture.expected.parts);
  });

  it("sorts object keys by Unicode code point", () => {
    expect(canonicalJson({ "\uE000": 1, "😀": 2 })).toBe('{"":1,"😀":2}');
  });

  it("rejects non-finite numbers", () => {
    expect(() => canonicalJson(Number.NaN)).toThrow("non-finite");
    expect(() => canonicalJson(Number.POSITIVE_INFINITY)).toThrow("non-finite");
  });
});
