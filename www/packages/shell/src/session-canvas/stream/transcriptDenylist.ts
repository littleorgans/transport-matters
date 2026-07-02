import type { TranscriptDenyRule } from "../../api";
import type { TranscriptMessageModel } from "./mapIrToChat";

/**
 * A transcript message paired with whether the denylist hides it. Used by the
 * transcript view to filter records by default while keeping them revealable.
 */
export interface AnnotatedTranscriptMessage {
  message: TranscriptMessageModel;
  hidden: boolean;
}

/**
 * Annotate each message with its denylist verdict, preserving order. An empty or
 * absent denylist is a no-op (every message visible), so the default reveals
 * everything with zero regression to the full-visibility view.
 *
 * Mirrors `read_transcript_denylist` matching in the backend: a record is hidden when
 * any rule matches its native payload.
 */
export function annotateDeniedMessages(
  messages: readonly TranscriptMessageModel[],
  denylist: readonly TranscriptDenyRule[] | undefined,
): AnnotatedTranscriptMessage[] {
  if (denylist === undefined || denylist.length === 0) {
    return messages.map((message) => ({ message, hidden: false }));
  }
  return messages.map((message) => ({
    message,
    hidden: isMessageDenied(message, denylist),
  }));
}

/** A message is denied when any rule matches its native payload. */
export function isMessageDenied(
  message: TranscriptMessageModel,
  denylist: readonly TranscriptDenyRule[],
): boolean {
  const payload = message.nativePayload;
  if (payload === null) return false;
  return denylist.some((rule) => ruleMatches(payload, rule));
}

/**
 * A rule matches when the value at its dotted `path` is present and, when `equals` is
 * set, equal to it. `equals` omitted or null means "match whenever the path exists".
 */
function ruleMatches(payload: Record<string, unknown>, rule: TranscriptDenyRule): boolean {
  const value = resolvePath(payload, rule.path);
  if (value === undefined) return false;
  return rule.equals === undefined || rule.equals === null ? true : value === rule.equals;
}

/** Resolve a dotted path through plain objects, returning undefined on any miss. */
function resolvePath(payload: Record<string, unknown>, path: string): unknown {
  let current: unknown = payload;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}
