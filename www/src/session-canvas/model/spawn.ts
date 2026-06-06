import type { WorldRect } from "../../engine";
import type { PaneContentRef, PaneRecord, SpawnSessionDescriptor, ViewerId } from "./paneRecords";

export const PICKER_PANE_ID = "session-picker";
export const TRANSCRIPT_PANE_PREFIX = "transcript:";

const PICKER_RECT: WorldRect = Object.freeze({ x: 48, y: 48, width: 440, height: 640 });
const TRANSCRIPT_RECT: WorldRect = Object.freeze({ x: 512, y: 48, width: 720, height: 640 });
const TRANSCRIPT_OFFSET = 28;

export function paneIdForRef(ref: PaneContentRef): string {
  return ref.kind === "session-picker"
    ? PICKER_PANE_ID
    : `${TRANSCRIPT_PANE_PREFIX}${ref.sessionId}`;
}

export function rectForRef(ref: PaneContentRef, existingPaneCount: number): WorldRect {
  if (ref.kind === "session-picker") return PICKER_RECT;
  const transcriptIndex = Math.max(0, existingPaneCount - 1);
  return {
    ...TRANSCRIPT_RECT,
    x: TRANSCRIPT_RECT.x + transcriptIndex * TRANSCRIPT_OFFSET,
    y: TRANSCRIPT_RECT.y + transcriptIndex * TRANSCRIPT_OFFSET,
  };
}

export function viewerIdForRef(ref: PaneContentRef): ViewerId {
  return ref.kind === "session-picker" ? "session-picker" : "transcript-chat";
}

export function titleForSession(session: SpawnSessionDescriptor): string {
  if (session.title && session.title.trim().length > 0) return session.title;
  const cli = session.cli ?? session.provider;
  return `${cli} session ${session.session_id.slice(0, 8)}`;
}

export function createPaneRecord(ref: PaneContentRef, title: string, now: string): PaneRecord {
  const paneId = paneIdForRef(ref);
  return {
    paneId,
    viewerId: viewerIdForRef(ref),
    title,
    contentRef: ref,
    chromeState: "default",
    createdAt: now,
    lastFocusedAt: null,
  };
}
