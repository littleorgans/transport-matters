import { describe, expect, it } from "vitest";
import { makeSessionEvent } from "../testUtils";
import { mapEventToTranscriptMessage } from "./mapIrToChat";

describe("mapEventToTranscriptMessage", () => {
  it("renders turn ir parts under the event role", () => {
    const message = mapEventToTranscriptMessage(
      makeSessionEvent({
        role: "user",
        ir: { parts: [{ type: "text", text: "prompt" }] },
      }),
    );

    expect(message?.role).toBe("user");
    expect(message?.blocks).toEqual([{ type: "text", text: "prompt", provider_data: null }]);
  });

  it("drops meta events with null ir", () => {
    expect(mapEventToTranscriptMessage(makeSessionEvent({ kind: "meta", ir: null }))).toBeNull();
  });

  it("handles artifact redacted image blocks", () => {
    const message = mapEventToTranscriptMessage(
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

  it("branches unknown kinds safely", () => {
    const message = mapEventToTranscriptMessage(makeSessionEvent({ kind: "signal", ir: null }));

    expect(message?.kind).toBe("unknown");
    expect(message?.blocks[0]?.type).toBe("unknown");
  });
});
