import { describe, expect, it } from "vitest";
import type {
  ContentBlock,
  InternalRequest,
  Message,
  OverrideAuditEntry,
  SamplingParams,
  ToolDef,
} from "../../types";
import {
  detectMessageMutations,
  detectMessageMutationsStructural,
  detectSamplingOverridesStructural,
  detectSystemPartMutations,
  detectSystemPartMutationsStructural,
  detectToolMutations,
  detectToolMutationsStructural,
  detectToolResultMutations,
} from "./mutations";

// Helpers keep the test payloads terse. We only exercise the fields
// the mutation detectors actually read (system, tools, messages and
// the shape of InternalRequest around them); the rest is zeroed out.
const SAMPLING: SamplingParams = {
  max_tokens: 0,
  temperature: null,
  top_p: null,
  top_k: null,
  stop_sequences: [],
};

function makeRequest(
  partial: Partial<
    Pick<InternalRequest, "system" | "tools" | "messages" | "sampling" | "provider_extras">
  > = {},
): InternalRequest {
  return {
    model: "",
    provider: "",
    system: partial.system ?? [],
    tools: partial.tools ?? [],
    messages: partial.messages ?? [],
    sampling: partial.sampling ?? SAMPLING,
    metadata: { session_id: null, device_id: null, account_id: null, provider_metadata: {} },
    stream: false,
    provider_extras: partial.provider_extras ?? {},
  };
}

function makeTool(name: string, description = ""): ToolDef {
  return { name, description, input_schema: {} };
}

function text(t: string): ContentBlock {
  return { type: "text", text: t };
}

function msg(role: "user" | "assistant", ...content: ContentBlock[]): Message {
  return { role, content };
}

function entry(
  kind: string,
  target: string,
  opts: { applied?: boolean; curated_value?: string | null; chars_delta?: number } = {},
): OverrideAuditEntry {
  return {
    kind,
    target,
    applied: opts.applied ?? true,
    chars_delta: opts.chars_delta ?? 0,
    curated_value: opts.curated_value ?? null,
  };
}

// ── Audit-driven detectors (primary path) ────────────────────────

describe("detectSystemPartMutations (audit-driven)", () => {
  it("returns nothing when audit is missing or empty", () => {
    expect(detectSystemPartMutations(undefined)).toEqual([]);
    expect(detectSystemPartMutations([])).toEqual([]);
  });

  it("emits deleted for applied system_part_toggle entries", () => {
    expect(detectSystemPartMutations([entry("system_part_toggle", "system:1")])).toEqual([
      { index: 1, kind: "deleted" },
    ]);
  });

  it("emits edited with curated_value for applied system_part_text", () => {
    expect(
      detectSystemPartMutations([entry("system_part_text", "system:2", { curated_value: "BETA" })]),
    ).toEqual([{ index: 2, kind: "edited", curatedText: "BETA" }]);
  });

  it("ignores unapplied entries", () => {
    expect(
      detectSystemPartMutations([
        entry("system_part_toggle", "system:0", { applied: false }),
        entry("system_part_text", "system:1", {
          applied: false,
          curated_value: "nope",
        }),
      ]),
    ).toEqual([]);
  });

  it("regression: disabling system:0 plus editing system:2 surfaces exactly two mutations", () => {
    // Pop-cascade: on the server, disabling system:0 shifts system:1 and
    // system:2 down by one in the curated array. The old structural
    // detector paired by raw index and flagged every following row as
    // an edit. The audit-driven path emits only what actually happened.
    const audit: OverrideAuditEntry[] = [
      entry("system_part_toggle", "system:0"),
      entry("system_part_text", "system:2", { curated_value: "rewritten" }),
    ];
    expect(detectSystemPartMutations(audit)).toEqual([
      { index: 0, kind: "deleted" },
      { index: 2, kind: "edited", curatedText: "rewritten" },
    ]);
  });
});

describe("detectToolMutations (audit-driven)", () => {
  it("returns nothing when audit is missing or empty", () => {
    expect(detectToolMutations(undefined)).toEqual([]);
    expect(detectToolMutations([])).toEqual([]);
  });

  it("emits disabled for applied tool_toggle", () => {
    expect(detectToolMutations([entry("tool_toggle", "tool:grep")])).toEqual([
      { name: "grep", kind: "disabled" },
    ]);
  });

  it("emits description_edited for applied tool_description with curated_value", () => {
    expect(
      detectToolMutations([
        entry("tool_description", "tool:bash", {
          curated_value: "Run bash (curated)",
        }),
      ]),
    ).toEqual([
      {
        name: "bash",
        kind: "description_edited",
        curatedDescription: "Run bash (curated)",
      },
    ]);
  });
});

describe("detectMessageMutations (audit-driven)", () => {
  it("returns nothing when audit is missing or empty", () => {
    expect(detectMessageMutations(undefined)).toEqual([]);
    expect(detectMessageMutations([])).toEqual([]);
  });

  it("emits disabled for applied message_block_toggle", () => {
    expect(detectMessageMutations([entry("message_block_toggle", "msg:0:blk:2")])).toEqual([
      { msgIdx: 0, blkIdx: 2, kind: "disabled" },
    ]);
  });

  it("emits edited with curated_value for applied message_text", () => {
    expect(
      detectMessageMutations([entry("message_text", "msg:1:blk:0", { curated_value: "WORLD" })]),
    ).toEqual([{ msgIdx: 1, blkIdx: 0, kind: "edited", curatedText: "WORLD" }]);
  });

  it("regression: dropping msg:0:blk:0 of a 5-block message plus editing msg:0:blk:3 surfaces exactly two mutations", () => {
    // The user's reported bug: one block disabled at the head of a
    // multi-block message plus one real text edit further down. The
    // old structural detector cascaded this into five false edits
    // because every surviving block shifted left in the curated array.
    // The audit-driven path resolves against originals-indexed targets
    // and emits only the two mutations the user actually made.
    const audit: OverrideAuditEntry[] = [
      entry("message_block_toggle", "msg:0:blk:0"),
      entry("message_text", "msg:0:blk:3", { curated_value: "..." }),
    ];
    expect(detectMessageMutations(audit)).toEqual([
      { msgIdx: 0, blkIdx: 0, kind: "disabled" },
      { msgIdx: 0, blkIdx: 3, kind: "edited", curatedText: "..." },
    ]);
  });

  it("ignores unapplied entries and entries missing curated_value", () => {
    const audit: OverrideAuditEntry[] = [
      entry("message_block_toggle", "msg:0:blk:0", { applied: false }),
      entry("message_text", "msg:0:blk:1", { applied: true, curated_value: null }),
      entry("message_text", "msg:0:blk:2", { applied: false, curated_value: "shouldn't land" }),
    ];
    expect(detectMessageMutations(audit)).toEqual([]);
  });

  it("skips malformed targets rather than throwing", () => {
    const audit: OverrideAuditEntry[] = [
      entry("message_text", "not:a:target", { curated_value: "x" }),
      entry("message_block_toggle", "msg:zero:blk:0"),
      entry("message_text", "msg:0:blk:0", { curated_value: "ok" }),
    ];
    expect(detectMessageMutations(audit)).toEqual([
      { msgIdx: 0, blkIdx: 0, kind: "edited", curatedText: "ok" },
    ]);
  });
});

describe("detectToolResultMutations (audit-driven)", () => {
  it("surfaces truncate_tool_result with curated text when the tool output changed", () => {
    const original = makeRequest({
      messages: [
        msg("assistant", { type: "tool_use", id: "tu-1", name: "bash", input: {} }),
        msg("user", {
          type: "tool_result",
          tool_use_id: "tu-1",
          content: [{ type: "text", text: "A".repeat(300) }],
          is_error: false,
        }),
      ],
    });
    const curated = makeRequest({
      messages: [
        msg("assistant", { type: "tool_use", id: "tu-1", name: "bash", input: {} }),
        msg("user", {
          type: "tool_result",
          tool_use_id: "tu-1",
          content: [{ type: "text", text: `${"A".repeat(100)} [truncated]` }],
          is_error: false,
        }),
      ],
    });

    expect(
      detectToolResultMutations(
        [
          entry("truncate_tool_result", "toolresult:tu-1", {
            curated_value: "stale audit text",
          }),
        ],
        original,
        curated,
      ),
    ).toEqual([{ toolUseId: "tu-1", curatedText: `${"A".repeat(100)} [truncated]` }]);
  });

  it("ignores truncate_tool_result when the curated text matches the original tool output", () => {
    const original = makeRequest({
      messages: [
        msg("assistant", { type: "tool_use", id: "tu-1", name: "bash", input: {} }),
        msg("user", {
          type: "tool_result",
          tool_use_id: "tu-1",
          content: [{ type: "text", text: "tiny" }],
          is_error: false,
        }),
      ],
    });

    expect(
      detectToolResultMutations(
        [entry("truncate_tool_result", "toolresult:tu-1", { curated_value: "tiny" })],
        original,
        original,
      ),
    ).toEqual([]);
  });

  it("ignores truncate_tool_result when the final curated request no longer contains that tool result", () => {
    const original = makeRequest({
      messages: [
        msg("assistant", { type: "tool_use", id: "tu-1", name: "bash", input: {} }),
        msg("user", {
          type: "tool_result",
          tool_use_id: "tu-1",
          content: [{ type: "text", text: "A".repeat(300) }],
          is_error: false,
        }),
      ],
    });
    const curated = makeRequest({
      messages: [msg("assistant", { type: "tool_use", id: "tu-1", name: "bash", input: {} })],
    });

    expect(
      detectToolResultMutations(
        [
          entry("truncate_tool_result", "toolresult:tu-1", {
            curated_value: `${"A".repeat(100)} [truncated]`,
          }),
        ],
        original,
        curated,
      ),
    ).toEqual([]);
  });
});

// ── Structural-diff fallback (manual-edit path) ──────────────────

describe("detectSystemPartMutationsStructural", () => {
  it("returns nothing when either side is missing", () => {
    expect(detectSystemPartMutationsStructural(undefined, undefined)).toEqual([]);
    expect(detectSystemPartMutationsStructural(makeRequest(), undefined)).toEqual([]);
    expect(detectSystemPartMutationsStructural(undefined, makeRequest())).toEqual([]);
  });

  it("pairs edits by index and carries the curated text", () => {
    const original = makeRequest({
      system: [
        { type: "text", text: "alpha" },
        { type: "text", text: "beta" },
      ],
    });
    const curated = makeRequest({
      system: [
        { type: "text", text: "alpha" },
        { type: "text", text: "BETA" },
      ],
    });
    expect(detectSystemPartMutationsStructural(original, curated)).toEqual([
      { index: 1, kind: "edited", curatedText: "BETA" },
    ]);
  });

  it("flags trailing originals as deleted when curated is shorter", () => {
    const original = makeRequest({
      system: [
        { type: "text", text: "alpha" },
        { type: "text", text: "beta" },
        { type: "text", text: "gamma" },
      ],
    });
    const curated = makeRequest({ system: [{ type: "text", text: "alpha" }] });
    expect(detectSystemPartMutationsStructural(original, curated)).toEqual([
      { index: 1, kind: "deleted" },
      { index: 2, kind: "deleted" },
    ]);
  });

  it("mixes edits and deletions when curated is a prefix with edits", () => {
    const original = makeRequest({
      system: [
        { type: "text", text: "alpha" },
        { type: "text", text: "beta" },
        { type: "text", text: "gamma" },
      ],
    });
    const curated = makeRequest({
      system: [
        { type: "text", text: "ALPHA" },
        { type: "text", text: "beta" },
      ],
    });
    expect(detectSystemPartMutationsStructural(original, curated)).toEqual([
      { index: 0, kind: "edited", curatedText: "ALPHA" },
      { index: 2, kind: "deleted" },
    ]);
  });
});

describe("detectToolMutationsStructural", () => {
  it("returns nothing when either side is missing", () => {
    expect(detectToolMutationsStructural(undefined, undefined)).toEqual([]);
    expect(detectToolMutationsStructural(makeRequest(), undefined)).toEqual([]);
  });

  it("flags removed tools as disabled", () => {
    const original = makeRequest({
      tools: [makeTool("bash", "Run bash"), makeTool("grep", "Search")],
    });
    const curated = makeRequest({ tools: [makeTool("bash", "Run bash")] });
    expect(detectToolMutationsStructural(original, curated)).toEqual([
      { name: "grep", kind: "disabled" },
    ]);
  });

  it("flags description changes and carries the curated description", () => {
    const original = makeRequest({
      tools: [makeTool("bash", "Run bash")],
    });
    const curated = makeRequest({
      tools: [makeTool("bash", "Run bash (curated)")],
    });
    expect(detectToolMutationsStructural(original, curated)).toEqual([
      {
        name: "bash",
        kind: "description_edited",
        curatedDescription: "Run bash (curated)",
      },
    ]);
  });

  it("ignores newly added tools in curated", () => {
    // New tools the pipeline injects aren't something the editor lets
    // the user create, so they aren't a mutation we need to surface.
    const original = makeRequest({ tools: [makeTool("bash", "Run bash")] });
    const curated = makeRequest({
      tools: [makeTool("bash", "Run bash"), makeTool("grep", "Search")],
    });
    expect(detectToolMutationsStructural(original, curated)).toEqual([]);
  });
});

describe("detectMessageMutationsStructural", () => {
  it("returns nothing when either side is missing", () => {
    expect(detectMessageMutationsStructural(undefined, undefined)).toEqual([]);
    expect(detectMessageMutationsStructural(makeRequest(), undefined)).toEqual([]);
    expect(detectMessageMutationsStructural(undefined, makeRequest())).toEqual([]);
  });

  it("returns nothing when messages are identical", () => {
    const original = makeRequest({
      messages: [msg("user", text("hi"), text("there")), msg("assistant", text("hello"))],
    });
    const curated = makeRequest({
      messages: [msg("user", text("hi"), text("there")), msg("assistant", text("hello"))],
    });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([]);
  });

  it("flags an edited text block with the curated text", () => {
    const original = makeRequest({ messages: [msg("user", text("hi"), text("world"))] });
    const curated = makeRequest({ messages: [msg("user", text("hi"), text("WORLD"))] });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([
      { msgIdx: 0, blkIdx: 1, kind: "edited", curatedText: "WORLD" },
    ]);
  });

  it("flags a block the pipeline dropped as disabled", () => {
    const original = makeRequest({ messages: [msg("user", text("a"), text("b"), text("c"))] });
    const curated = makeRequest({ messages: [msg("user", text("a"), text("b"))] });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([
      { msgIdx: 0, blkIdx: 2, kind: "disabled" },
    ]);
  });

  it("mixes edits and disables across multiple messages", () => {
    const original = makeRequest({
      messages: [
        msg("user", text("alpha"), text("beta"), text("gamma")),
        msg("assistant", text("ack"), text("follow")),
      ],
    });
    const curated = makeRequest({
      messages: [msg("user", text("ALPHA"), text("beta")), msg("assistant", text("ack"))],
    });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([
      { msgIdx: 0, blkIdx: 0, kind: "edited", curatedText: "ALPHA" },
      { msgIdx: 0, blkIdx: 2, kind: "disabled" },
      { msgIdx: 1, blkIdx: 1, kind: "disabled" },
    ]);
  });

  it("disables every block when a whole message is dropped", () => {
    const original = makeRequest({
      messages: [msg("user", text("keep")), msg("assistant", text("drop-a"), text("drop-b"))],
    });
    const curated = makeRequest({ messages: [msg("user", text("keep"))] });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([
      { msgIdx: 1, blkIdx: 0, kind: "disabled" },
      { msgIdx: 1, blkIdx: 1, kind: "disabled" },
    ]);
  });

  it("ignores trailing curated-only blocks and messages", () => {
    // The editor can't add messages or blocks, so extra curated entries
    // beyond the original length aren't surfaced as mutations.
    const original = makeRequest({ messages: [msg("user", text("one"))] });
    const curated = makeRequest({
      messages: [msg("user", text("one"), text("two")), msg("assistant", text("ghost"))],
    });
    expect(detectMessageMutationsStructural(original, curated)).toEqual([]);
  });

  it("only emits curatedText for text blocks", () => {
    // Non-text blocks aren't editable through the override layer, so a
    // same-index non-text block that happens to differ shouldn't carry
    // a curatedText payload — the Inspect view has no surface for it.
    const original: Message = {
      role: "assistant",
      content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
    };
    const curated: Message = {
      role: "assistant",
      content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "pwd" } }],
    };
    expect(
      detectMessageMutationsStructural(
        makeRequest({ messages: [original] }),
        makeRequest({ messages: [curated] }),
      ),
    ).toEqual([]);
  });
});

describe("detectSamplingOverridesStructural", () => {
  it("emits sampling_set overrides only for fields whose curated values differ", () => {
    const original = makeRequest({
      sampling: {
        max_tokens: 1024,
        temperature: null,
        top_p: null,
        top_k: null,
        stop_sequences: [],
      },
    });
    const curated = makeRequest({
      sampling: {
        max_tokens: 2048,
        temperature: 0.2,
        top_p: null,
        top_k: null,
        stop_sequences: ["END"],
      },
    });

    expect(detectSamplingOverridesStructural(original, curated)).toEqual([
      { kind: "sampling_set", target: "sampling:max_tokens", value: 2048 },
      { kind: "sampling_set", target: "sampling:temperature", value: 0.2 },
      { kind: "sampling_set", target: "sampling:stop_sequences", value: '["END"]' },
    ]);
  });

  it("emits provider_extras_set overrides for thinking, display, and effort differences", () => {
    const original = makeRequest({
      provider_extras: {
        thinking: { type: "adaptive", display: "summarized" },
        output_config: { effort: "medium" },
      },
    });
    const curated = makeRequest({
      provider_extras: {
        thinking: { type: "enabled", budget_tokens: 8192, display: "omitted" },
        output_config: { effort: "high" },
      },
    });

    expect(detectSamplingOverridesStructural(original, curated)).toEqual([
      {
        kind: "provider_extras_set",
        target: "provider_extras:thinking",
        value: '{"type":"enabled","budget_tokens":8192,"display":"omitted"}',
      },
      {
        kind: "provider_extras_set",
        target: "provider_extras:thinking.display",
        value: '"omitted"',
      },
      {
        kind: "provider_extras_set",
        target: "provider_extras:output_config.effort",
        value: '"high"',
      },
    ]);
  });
});
