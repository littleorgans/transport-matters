import { paneIdForRef, viewerIdForRef } from "../viewers/registry";
import type {
  PaneContentRef,
  PaneRecord,
  SpawnablePaneRef,
  SpawnSessionDescriptor,
} from "./paneRecords";

/**
 * Aliases the legacy `{ kind: "session" }` ref onto `session-timeline`. Because
 * both resolve to the same registry pane id, an already-open session pane is
 * reused rather than duplicated.
 */
export function normalizeRef(ref: SpawnablePaneRef): PaneContentRef {
  if (ref.kind === "session") {
    return { kind: "session-timeline", owner: ref.owner, sessionId: ref.sessionId };
  }
  return ref;
}

export function titleForSession(session: SpawnSessionDescriptor): string {
  if (session.title && session.title.trim().length > 0) return session.title;
  const cli = session.cli ?? session.provider;
  return `${cli} session ${session.session_id.slice(0, 8)}`;
}

export function createPaneRecord(ref: PaneContentRef, title: string, now: string): PaneRecord {
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
