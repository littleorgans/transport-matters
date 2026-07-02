import { describe, expect, it } from "vitest";
import { makeSessionEvent } from "../testUtils";
import type { TranscriptMessageModel } from "./mapIrToChat";
import { mapSessionEventToChatItems } from "./mapIrToChat";
import { annotateDeniedMessages, isMessageDenied } from "./transcriptDenylist";

function messageWithPayload(
  nativePayload: Record<string, unknown> | null,
  seq = 0,
): TranscriptMessageModel {
  const [message] = mapSessionEventToChatItems(makeSessionEvent({ nativePayload, seq }));
  if (message === undefined) throw new Error("expected a transcript message");
  return message;
}

describe("transcript denylist matching", () => {
  it("hides a record whose dotted path equals the rule value", () => {
    const message = messageWithPayload({
      type: "attachment",
      attachment: { type: "output_style" },
    });
    expect(isMessageDenied(message, [{ path: "attachment.type", equals: "output_style" }])).toBe(
      true,
    );
  });

  it("keeps a record when the equality value differs", () => {
    const message = messageWithPayload({
      type: "attachment",
      attachment: { type: "hook_success" },
    });
    expect(isMessageDenied(message, [{ path: "attachment.type", equals: "output_style" }])).toBe(
      false,
    );
  });

  it("matches on path presence when equals is omitted", () => {
    const message = messageWithPayload({ type: "summary" });
    expect(isMessageDenied(message, [{ path: "type" }])).toBe(true);
  });

  it("never hides a record with a null native payload", () => {
    expect(isMessageDenied(messageWithPayload(null), [{ path: "type" }])).toBe(false);
  });

  it("treats an empty or absent denylist as a no-op", () => {
    const message = messageWithPayload({ type: "user" });
    expect(annotateDeniedMessages([message], [])).toEqual([{ message, hidden: false }]);
    expect(annotateDeniedMessages([message], undefined)).toEqual([{ message, hidden: false }]);
  });

  it("annotates each message with its verdict, preserving order", () => {
    const kept = messageWithPayload({ type: "user" }, 1);
    const hidden = messageWithPayload(
      { type: "attachment", attachment: { type: "output_style" } },
      2,
    );
    const annotated = annotateDeniedMessages(
      [kept, hidden],
      [{ path: "attachment.type", equals: "output_style" }],
    );
    expect(annotated.map((item) => item.hidden)).toEqual([false, true]);
  });
});
