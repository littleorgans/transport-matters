import type { HarnessName } from "../../types";
import { paneIdForRef, viewerIdForRef } from "../viewers/registry";
import { createCapturedRunKey } from "./capturedRunStore";
import type {
  CanvasPaneRef,
  PaneContentRef,
  PaneRecord,
  SpawnablePaneRef,
  SpawnSessionDescriptor,
} from "./paneRecords";

type CapturedRunRef = Extract<PaneContentRef, { kind: "captured-run" }>;

/**
 * Aliases the legacy `{ kind: "session" }` ref onto `session-timeline`. Because
 * both resolve to the same registry pane id, an already-open session pane is
 * reused rather than duplicated.
 */
export function normalizeRef(ref: SpawnablePaneRef): CanvasPaneRef {
  if (ref.kind === "session") {
    return { kind: "session-timeline", owner: ref.owner, sessionId: ref.sessionId };
  }
  return ref;
}

export function titleForSession(session: SpawnSessionDescriptor): string {
  if (session.title && session.title.trim().length > 0) return session.title;
  return `${session.harness} session ${session.sessionId.slice(0, 8)}`;
}

export function createCapturedRunRef(
  provider: HarnessName,
  label?: string,
  runtimeTemplate?: string,
): CapturedRunRef {
  return {
    kind: "captured-run",
    owner: "local",
    provider,
    runKey: createCapturedRunKey(provider),
    ...(label === undefined ? {} : { label }),
    ...(runtimeTemplate === undefined ? {} : { runtimeTemplate }),
  };
}

export function createPaneRecord(ref: CanvasPaneRef, title: string, now: string): PaneRecord {
  return {
    paneId: paneIdForRef(ref),
    viewerId: viewerIdForRef(ref),
    title,
    contentRef: ref,
    chromeState: "default",
    createdAt: now,
    lastFocusedAt: null,
  };
}
