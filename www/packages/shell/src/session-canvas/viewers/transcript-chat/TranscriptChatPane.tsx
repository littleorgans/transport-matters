import { useMeta } from "@tm/core";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import type { SessionEventView } from "../../api/sessionEvents";
import { useSessionEvents } from "../../hooks/useSessionEvents";
import type { ViewerProps } from "../../model/paneRecords";
import { mapSessionEventToChatItems } from "../../stream/mapIrToChat";
import { createSessionEventState, sessionEventReducer } from "../../stream/sessionEventReducer";
import { annotateDeniedMessages } from "../../stream/transcriptDenylist";
import { useSessionEventStream } from "../../stream/useSessionEventStream";
import { TranscriptMessage } from "./TranscriptMessage";

export function TranscriptChatPane({
  pane,
}: ViewerProps<{ kind: "session-timeline"; owner: "local"; sessionId: string }>) {
  const sessionId = pane.contentRef.sessionId;
  const [state, dispatch] = useReducer(sessionEventReducer, sessionId, createSessionEventState);
  const backlog = useSessionEvents({ owner: "local", sessionId });
  const appendEvents = useCallback(
    (events: SessionEventView[]) => dispatch({ type: "append", sessionId, events }),
    [sessionId],
  );
  const stream = useSessionEventStream({
    enabled: backlog.isSuccess,
    highestSeq: state.highestSeq,
    onEvents: appendEvents,
    owner: "local",
    sessionId,
  });

  useEffect(() => {
    dispatch({ type: "reset", sessionId, events: [] });
  }, [sessionId]);

  useEffect(() => {
    if (backlog.data) {
      dispatch({ type: "reset", sessionId, events: backlog.data.events });
    }
  }, [backlog.data, sessionId]);

  const { meta } = useMeta();
  const messages = useMemo(() => state.events.flatMap(mapSessionEventToChatItems), [state.events]);
  const annotated = useMemo(
    () => annotateDeniedMessages(messages, meta?.transcriptDenylist),
    [messages, meta?.transcriptDenylist],
  );
  const hiddenCount = useMemo(
    () => annotated.reduce((count, item) => count + (item.hidden ? 1 : 0), 0),
    [annotated],
  );
  const [showHidden, setShowHidden] = useState(false);
  const visible = useMemo(
    () => (showHidden ? annotated : annotated.filter((item) => !item.hidden)),
    [annotated, showHidden],
  );

  if (backlog.isLoading) return <TranscriptLoading />;
  if (backlog.error)
    return <TranscriptError error={backlog.error} onRetry={() => void backlog.refetch()} />;
  if (messages.length === 0) return <TranscriptEmpty connected={stream.connected} />;

  return (
    <div className="canvas-transcript">
      <TranscriptStatus
        connected={stream.connected}
        missingFromSeq={state.missingFromSeq}
        hiddenCount={hiddenCount}
        showHidden={showHidden}
        onToggleHidden={() => setShowHidden((current) => !current)}
      />
      <div className="canvas-transcript__messages">
        {visible.map((item) => (
          <TranscriptMessage key={item.message.id} message={item.message} hidden={item.hidden} />
        ))}
      </div>
    </div>
  );
}

function TranscriptStatus({
  connected,
  missingFromSeq,
  hiddenCount,
  showHidden,
  onToggleHidden,
}: {
  connected: boolean;
  missingFromSeq: number | null;
  hiddenCount: number;
  showHidden: boolean;
  onToggleHidden(): void;
}) {
  return (
    <div className="canvas-transcript__status" aria-live="polite">
      <span>{connected ? "live" : "reconnecting"}</span>
      {missingFromSeq !== null ? <span>gap from seq {missingFromSeq}</span> : null}
      {hiddenCount > 0 ? (
        <button
          type="button"
          className="canvas-transcript__filter-toggle"
          aria-pressed={showHidden}
          onClick={onToggleHidden}
        >
          {showHidden ? `hide ${hiddenCount} filtered` : `show ${hiddenCount} filtered`}
        </button>
      ) : null}
    </div>
  );
}

function TranscriptLoading() {
  return (
    <div className="canvas-transcript canvas-transcript--center" aria-busy="true">
      <div className="canvas-picker__skeleton" />
      <div className="canvas-picker__skeleton" />
    </div>
  );
}

function TranscriptError({ error, onRetry }: { error: Error; onRetry(): void }) {
  return (
    <div className="canvas-transcript canvas-transcript--center" role="alert">
      <p>Transcript failed to load.</p>
      <p className="canvas-picker__hint">{error.message}</p>
      <button className="canvas-button" onClick={onRetry} type="button">
        Retry
      </button>
    </div>
  );
}

function TranscriptEmpty({ connected }: { connected: boolean }) {
  return (
    <div className="canvas-transcript canvas-transcript--center">
      <p>No transcript events yet.</p>
      <p className="canvas-picker__hint">Stream is {connected ? "live" : "reconnecting"}.</p>
    </div>
  );
}
