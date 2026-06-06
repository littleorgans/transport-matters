import { describe, expect, it } from "vitest";
import { makeSessionEvent } from "../testUtils";
import { mapSessionEventToChatItems } from "./mapIrToChat";

describe("mapSessionEventToChatItems", () => {
  it("renders turn ir parts under the event role", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        role: "user",
        ir: { parts: [{ type: "text", text: "prompt" }] },
      }),
    );

    expect(message?.role).toBe("user");
    expect(message?.blocks).toEqual([{ type: "text", text: "prompt", provider_data: null }]);
  });

  it("renders meta events from event fields without ir", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        kind: "meta",
        ir: null,
        model: "claude-sonnet",
        native_turn_id: "native-7",
        role: null,
        seq: 7,
        source_line: 42,
        source_path: "/tmp/source.jsonl",
        ts: "2026-06-06T18:00:00Z",
      }),
    );

    expect(message?.kind).toBe("meta");
    expect(message?.role).toBe("metadata");
    expect(message?.blocks[0]).toEqual({
      type: "text",
      text: [
        "kind: meta",
        "seq: 7",
        "native_turn_id: native-7",
        "ts: 2026-06-06T18:00:00Z",
        "model: claude-sonnet",
        "source_path: /tmp/source.jsonl",
        "source_line: 42",
      ].join("\n"),
      provider_data: null,
    });
  });

  it("handles artifact redacted image blocks", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({
        ir: { parts: [{ type: "image", artifact_hash: "sha256:abc", media_type: "image/png" }] },
      }),
    );

    expect(message?.blocks[0]).toEqual({
      type: "image",
      source: { artifact_hash: "sha256:abc", media_type: "image/png", redacted: true },
      provider_data: null,
    });
  });

  it("uses search text when a turn has no renderable parts", () => {
    const [message] = mapSessionEventToChatItems(
      makeSessionEvent({ ir: { parts: [] }, search_text: "fallback text" }),
    );

    expect(message?.blocks).toEqual([{ type: "text", text: "fallback text", provider_data: null }]);
  });

  it("branches unknown kinds safely", () => {
    const [message] = mapSessionEventToChatItems(makeSessionEvent({ kind: "signal", ir: null }));

    expect(message?.kind).toBe("unknown");
    expect(message?.blocks[0]?.type).toBe("text");
  });
});
