import { describe, expect, it } from "vitest";
import type { ExchangeDetail, InternalRequest } from "../types";
import {
  buildExportFilename,
  buildExportHtml,
  collectStyles,
  serializeInspect,
} from "./exportInspect";

const longSystemPart =
  "system-export-completeness " +
  "The complete system prompt must survive HTML export without truncation or textarea loss. ".repeat(
    5,
  );
const longToolDescription =
  "tool-export-completeness " +
  "The complete tool description must survive HTML export without truncation or textarea loss. ".repeat(
    5,
  );

function makeDetail(): ExchangeDetail {
  const request = {
    model: "claude-sonnet-4",
    provider: "anthropic",
    system: [{ type: "text", text: longSystemPart }],
    tools: [
      {
        name: "read_file",
        description: longToolDescription,
        input_schema: {
          type: "object",
          properties: { path: { type: "string" } },
          required: ["path"],
        },
      },
    ],
    messages: [{ role: "user", content: [{ type: "text", text: "Read the file." }] }],
    sampling: {
      max_tokens: 4096,
      temperature: null,
      top_p: null,
      top_k: null,
      stop_sequences: [],
    },
    metadata: {
      session_id: "session-1",
      device_id: null,
      account_id: null,
      provider_metadata: {},
    },
    stream: true,
    provider_extras: {},
  } satisfies InternalRequest;

  return {
    entry: {
      id: "exchange/123",
      ts: "2026-06-04T00:00:00.000Z",
      provider: "anthropic",
      model: "claude/sonnet 4",
      path: "/tmp/session",
      req: {
        system_parts: request.system.length,
        system_chars: longSystemPart.length,
        tools_count: request.tools.length,
        tools_chars: longToolDescription.length,
        messages_count: request.messages.length,
        messages_chars: "Read the file.".length,
        total_chars: longSystemPart.length + longToolDescription.length + "Read the file.".length,
      },
      pipeline: null,
      res: {
        stop_reason: "end_turn",
        input_tokens: 10,
        output_tokens: 5,
        cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0,
        text_chars: 24,
        tool_calls: 0,
      },
      mutated_manually: false,
    },
    request_ir: request,
    request_curated_ir: null,
    request_audit: null,
    response_ir: {
      content: [{ type: "text", text: "The file was read successfully." }],
    },
    transport: null,
    events: null,
    turn: null,
    codex_derived_artifacts: null,
    transport_diagnostics: [],
  };
}

describe("serializeInspect", () => {
  it("preserves full textarea-backed system parts and tool descriptions", () => {
    const html = serializeInspect(makeDetail());

    expect(longSystemPart.length).toBeGreaterThan(200);
    expect(longToolDescription.length).toBeGreaterThan(200);
    expect(html).toContain(longSystemPart);
    expect(html).toContain(longToolDescription);
  });
});

describe("buildExportHtml", () => {
  it("builds a complete standalone Inspect export", () => {
    const detail = makeDetail();
    const html = buildExportHtml({
      contentHtml: `<section>${longSystemPart}</section>`,
      css: ".card{display:block}",
      detail,
    });

    expect(longSystemPart.length).toBeGreaterThan(200);
    expect(html).toContain(longSystemPart);
    expect(html).toContain("<style>");
    expect(html).toMatch(/<details(?![^>]*\sopen\b)[^>]*>\s*<summary[^>]*>Raw JSON<\/summary>/);
    expect(html).toContain("addEventListener");
  });

  it("sanitizes provider, model, and exchange id in filenames", () => {
    expect(buildExportFilename(makeDetail())).toBe(
      "transport-matters-anthropic-claude-sonnet-4-exchange-123.html",
    );
  });
});

describe("collectStyles", () => {
  it("skips unreadable stylesheets without dropping readable sheets", () => {
    const blockedSheet = {};
    Object.defineProperty(blockedSheet, "cssRules", {
      get() {
        throw new DOMException("Blocked", "SecurityError");
      },
    });
    const sourceDocument = {
      styleSheets: [blockedSheet, { cssRules: [{ cssText: ".ok{display:block}" }] }],
    } as unknown as Document;

    expect(collectStyles(sourceDocument)).toBe(".ok{display:block}");
  });
});
