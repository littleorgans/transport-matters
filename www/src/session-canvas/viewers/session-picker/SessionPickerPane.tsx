import { useEffect, useMemo, useState } from "react";
import { displayCwd, formatRelativeAge } from "../../../lib/formatting";
import type { SessionSummary } from "../../api/sessionClient";
import { useSessions } from "../../hooks/useSessions";
import type { ViewerProps } from "../../model/paneRecords";

export function SessionPickerPane({
  canvas,
  actions,
}: ViewerProps<{ kind: "session-picker"; owner: "local" }>) {
  const { data, error, isLoading, refetch } = useSessions({
    owner: "local",
    workspaceHash: canvas.workspaceHash,
    limit: 50,
    offset: 0,
  });
  const sessions = data ?? [];
  const [activeIndex, setActiveIndex] = useState(0);
  const hasLaunchPending = canvas.launchStatus === "pending";
  const activeSession = sessions[activeIndex];

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, sessions.length - 1)));
  }, [sessions.length]);

  const pendingLabel = useMemo(() => {
    if (!hasLaunchPending) return null;
    return `Waiting for live ${canvas.launch.cli ?? "agent"} session`;
  }, [canvas.launch.cli, hasLaunchPending]);

  if (isLoading) return <SessionPickerSkeleton pendingLabel={pendingLabel} />;
  if (error) return <SessionPickerError error={error} onRetry={() => void refetch()} />;
  if (sessions.length === 0) {
    return <SessionPickerEmpty onRefresh={() => void refetch()} pendingLabel={pendingLabel} />;
  }

  return (
    <fieldset
      className="canvas-picker"
      onKeyDown={(event) =>
        handlePickerKey(
          event,
          sessions,
          activeIndex,
          setActiveIndex,
          actions.spawnOrFocusTranscript,
        )
      }
    >
      <legend className="sr-only">Session picker</legend>
      <div className="canvas-picker__summary" aria-live="polite">
        <span>{sessions.length} sessions</span>
        {pendingLabel ? <span>{pendingLabel}</span> : null}
      </div>
      <div className="canvas-picker__list">
        {sessions.map((session, index) => (
          <button
            aria-current={index === activeIndex ? "true" : undefined}
            className="canvas-picker__row"
            data-active={index === activeIndex}
            key={session.session_id}
            onClick={() => actions.spawnOrFocusTranscript(session)}
            onFocus={() => setActiveIndex(index)}
            type="button"
          >
            <SessionRow session={session} live={session.session_id === canvas.launchSessionId} />
          </button>
        ))}
      </div>
      {activeSession ? (
        <p className="canvas-picker__hint">
          Press Enter to open {activeSession.title ?? activeSession.cli ?? activeSession.provider}.
        </p>
      ) : null}
    </fieldset>
  );
}

function SessionRow({ session, live }: { session: SessionSummary; live: boolean }) {
  const title = session.title ?? `${session.cli ?? session.provider} session`;
  const started = formatRelativeAge(session.started_at);
  return (
    <span className="canvas-picker__row-inner">
      <span className="canvas-picker__row-title">
        <span>{title}</span>
        {live ? <span className="canvas-live-badge">live</span> : null}
      </span>
      <span className="canvas-picker__row-meta">
        <span>{session.provider}</span>
        <span>{session.cli ?? "cli unknown"}</span>
        <span>{session.status}</span>
        <span>{started}</span>
      </span>
      <span className="canvas-picker__row-cwd">{displayCwd(session.cwd)}</span>
      {session.native_session_id ? (
        <span className="canvas-picker__row-native">native {session.native_session_id}</span>
      ) : null}
    </span>
  );
}

function SessionPickerSkeleton({ pendingLabel }: { pendingLabel: string | null }) {
  return (
    <div className="canvas-picker" aria-busy="true">
      {pendingLabel ? <p className="canvas-picker__pending">{pendingLabel}</p> : null}
      <div className="canvas-picker__skeleton" />
      <div className="canvas-picker__skeleton" />
      <div className="canvas-picker__skeleton" />
    </div>
  );
}

function SessionPickerError({ error, onRetry }: { error: Error; onRetry(): void }) {
  return (
    <div className="canvas-picker canvas-picker--center" role="alert">
      <p>Session lookup failed.</p>
      <p className="canvas-picker__hint">{error.message}</p>
      <button className="canvas-button" onClick={onRetry} type="button">
        Retry
      </button>
    </div>
  );
}

function SessionPickerEmpty({
  onRefresh,
  pendingLabel,
}: {
  onRefresh(): void;
  pendingLabel: string | null;
}) {
  return (
    <div className="canvas-picker canvas-picker--center">
      <p>{pendingLabel ?? "No sessions found for this canvas."}</p>
      <button className="canvas-button" onClick={onRefresh} type="button">
        Refresh
      </button>
    </div>
  );
}

function handlePickerKey(
  event: React.KeyboardEvent,
  sessions: readonly SessionSummary[],
  activeIndex: number,
  setActiveIndex: (value: number | ((current: number) => number)) => void,
  openSession: (session: SessionSummary) => void,
): void {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setActiveIndex((current) => Math.min(sessions.length - 1, current + 1));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setActiveIndex((current) => Math.max(0, current - 1));
  } else if (event.key === "Enter") {
    event.preventDefault();
    const session = sessions[activeIndex];
    if (session) openSession(session);
  }
}
