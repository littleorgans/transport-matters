import { describe, expect, it } from "vitest";
import { classifyPreview } from "./ExchangePreview";

describe("classifyPreview", () => {
  it("classifies plain text", () => {
    const result = classifyPreview("write me a function that parses JSON");
    expect(result.kind).toBe("plain");
    expect(result.pill).toBeNull();
    expect(result.mono).toBe(false);
    expect(result.body).toBe("write me a function that parses JSON");
  });

  it("classifies and pretty-prints valid JSON", () => {
    const result = classifyPreview('{"status":"ok","items":[1,2,3]}');
    expect(result.kind).toBe("json");
    expect(result.pill).toBe("JSON");
    expect(result.mono).toBe(true);
    expect(result.body).toContain('"status": "ok"');
    expect(result.body.split("\n").length).toBeLessThanOrEqual(6);
  });

  it("truncates JSON pretty-print to 5 lines plus ellipsis", () => {
    const long = JSON.stringify({ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8 }, null, 2);
    const result = classifyPreview(long);
    expect(result.kind).toBe("json");
    const lines = result.body.split("\n");
    expect(lines.length).toBe(6);
    expect(lines[5]).toBe("\u2026");
  });

  it("falls back to mono raw when JSON-like text fails to parse", () => {
    const result = classifyPreview("{ malformed: json }");
    expect(result.kind).toBe("json");
    expect(result.mono).toBe(true);
    expect(result.body).toContain("malformed");
  });

  it("classifies fenced code with language", () => {
    const result = classifyPreview("```python\ndef hello():\n    pass\n```");
    expect(result.kind).toBe("code");
    expect(result.pill).toBe("PYTHON");
    expect(result.mono).toBe(true);
    expect(result.body).toBe("def hello():\n    pass");
  });

  it("classifies fenced code without language", () => {
    const result = classifyPreview("```\nplain code\n```");
    expect(result.kind).toBe("code");
    expect(result.pill).toBe("CODE");
    expect(result.body).toBe("plain code");
  });

  it("classifies XML-tagged content and extracts tag pill", () => {
    const result = classifyPreview("<thinking>let me reason about this...</thinking>");
    expect(result.kind).toBe("xml");
    expect(result.pill).toBe("THINKING");
    expect(result.mono).toBe(false);
    expect(result.body).toBe("let me reason about this...");
  });

  it("classifies XML opening tag without close", () => {
    const result = classifyPreview("<answer>partial body content");
    expect(result.kind).toBe("xml");
    expect(result.pill).toBe("ANSWER");
    expect(result.body).toBe("partial body content");
  });

  it("does not match XML on comparison-like text", () => {
    const result = classifyPreview("< 5 items remaining");
    expect(result.kind).toBe("plain");
    expect(result.pill).toBeNull();
  });

  it("trims surrounding whitespace before classification", () => {
    const result = classifyPreview("\n\n  hello world  \n");
    expect(result.kind).toBe("plain");
    expect(result.body).toBe("hello world");
  });

  it("returns empty body for whitespace-only input", () => {
    const result = classifyPreview("   \n  \t");
    expect(result.kind).toBe("plain");
    expect(result.body).toBe("");
  });
});
