import type { HarnessName } from "@tm/core/types/capabilities";
import type { SessionSummary } from "./api/sessionClient";
import { type CapturedRunKey, useCapturedRunStore } from "./model/capturedRunStore";
import type { PaneContentRef } from "./model/paneRecords";

// The transport mock harness lives with the seam it mocks; re-exported here
// so canvas tests keep one import site.
export {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "@tm/core/testing";

export function makeCapturedRunRef(
  runKey: CapturedRunKey = "claude:k1",
  provider: HarnessName = "claude",
  worktreeId = "wt-test",
): Extract<PaneContentRef, { kind: "captured-run" }> {
  return { kind: "captured-run", owner: "local", provider, runKey, worktreeId };
}

export function rememberCapturedRun(
  runKey: CapturedRunKey = "claude:k1",
  runId = "run-1",
  provider: HarnessName = "claude",
): void {
  useCapturedRunStore.setState((state) => ({
    runs: { ...state.runs, [runKey]: { provider, runId } },
  }));
}

export function makeSessionSummary(patch: Partial<SessionSummary> = {}): SessionSummary {
  return {
    sessionId: patch.sessionId ?? "session-1",
    workspaceId: patch.workspaceId ?? "project/hash-1",
    title: patch.title ?? "Project agent",
    status: patch.status ?? "active",
    provider: patch.provider ?? "anthropic",
    harness: patch.harness ?? "claude",
    createdAt: patch.createdAt ?? "2026-06-06T17:00:00Z",
    lastActivityAt: patch.lastActivityAt ?? "2026-06-06T17:01:00Z",
    purpose: patch.purpose ?? "user",
    visibility: patch.visibility ?? "user_visible",
    lineage: patch.lineage ?? {
      parentSessionId: null,
      forkedAtSeq: null,
      forkedAtTurn: null,
    },
    turnCount: patch.turnCount ?? 1,
    inheritedTurnCount: patch.inheritedTurnCount ?? 0,
    lastMessagePreview: patch.lastMessagePreview ?? "hello transcript",
  };
}

export function makeSessionEvent(
  patch: Partial<import("./api/sessionEvents").SessionEventView> = {},
): import("./api/sessionEvents").SessionEventView {
  return {
    seq: patch.seq ?? 0,
    turnIndex: patch.turnIndex ?? 1,
    kind: patch.kind ?? "turn",
    role: patch.role ?? "assistant",
    ts: patch.ts ?? "2026-06-06T17:00:00Z",
    body: patch.body ?? {
      kind: "assistant",
      parts: [{ type: "text", text: "hello transcript" }],
    },
    nativePayload:
      patch.nativePayload === null
        ? null
        : (patch.nativePayload ?? { type: "message", text: "hello transcript" }),
    resourceRefs: patch.resourceRefs ?? [],
  };
}
