import { describe, expect, it } from "vitest";
import { makeSessionEvent } from "../testUtils";
import { mapSessionEventToChatItems } from "./mapIrToChat";

describe("mapSessionEventToChatItems", () => {
  it("renders transcript body parts under the event role", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        role: "user",
        body: { kind: "user", parts: [{ type: "text", text: "prompt" }] },
      }),
    );

    expect(message?.role).toBe("user");
    expect(message?.blocks).toEqual([{ type: "text", text: "prompt", provider_data: null }]);
  });

  it("preserves wire context turns with their label", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        role: "system",
        body: {
          kind: "wire_injected",
          label: "System reminder",
          parts: [{ type: "text", text: "remember the policy" }],
        },
      }),
    );

    expect(message?.kind).toBe("wire_context");
    expect(message?.role).toBe("wire");
    expect(message?.wireLabel).toBe("System reminder");
    expect(message?.blocks).toEqual([
      { type: "text", text: "remember the policy", provider_data: null },
    ]);
  });

  it("renders meta events from native payload", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        kind: "meta",
        role: null,
        seq: 7,
        turnIndex: 3,
        ts: "2026-06-06T18:00:00Z",
        body: { kind: "wire_injected", label: "meta", parts: [] },
        nativePayload: {
          type: "session_meta",
          payload: { id: "native-1", cwd: "/workspace" },
        },
      }),
    );

    expect(message?.kind).toBe("meta");
    expect(message?.role).toBe("metadata");
    expect(message?.blocks[0]).toEqual({
      type: "text",
      text: JSON.stringify(
        {
          type: "session_meta",
          payload: { id: "native-1", cwd: "/workspace" },
        },
        null,
        2,
      ),
      provider_data: null,
    });
  });

  it("renders empty wire injected cards from native payload", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        role: "system",
        body: { kind: "wire_injected", label: "Hook success", parts: [] },
        nativePayload: {
          type: "attachment",
          attachment: {
            type: "hook_success",
            command: "pwd",
            stdout: "Injected reminder text",
          },
        },
      }),
    );

    expect(message?.kind).toBe("wire_context");
    expect(message?.blocks[0]).toEqual({
      type: "text",
      text: JSON.stringify(
        {
          type: "attachment",
          attachment: {
            type: "hook_success",
            command: "pwd",
            stdout: "Injected reminder text",
          },
        },
        null,
        2,
      ),
      provider_data: null,
    });
  });

  it("renders tool calls as readable text", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        body: { kind: "tool_use", toolName: "Read", input: { file: "a.ts" } },
      }),
    );

    expect(message?.blocks[0]?.type).toBe("text");
    const [block] = message?.blocks ?? [];
    const text = block !== undefined && "text" in block ? block.text : "";
    expect(text).toContain("tool_use: Read");
  });

  it("renders tool results as readable text", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        body: { kind: "tool_result", toolName: "Read", output: "contents", isError: false },
      }),
    );

    expect(message?.blocks[0]?.type).toBe("text");
    const [block] = message?.blocks ?? [];
    const text = block !== undefined && "text" in block ? block.text : "";
    expect(text).toContain("tool_result: Read");
    expect(text).toContain("contents");
  });

  it("branches unknown kinds safely", () => {
    const [message] = mapSessionEventToChatItems(makeSessionEvent({ kind: "signal" }));

    expect(message?.kind).toBe("unknown");
    expect(message?.blocks[0]?.type).toBe("text");
  });
});
