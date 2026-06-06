import type { SessionEventView } from "../api/sessionEvents";

export interface SessionEventState {
  sessionId: string;
  events: SessionEventView[];
  highestSeq: number;
  missingFromSeq: number | null;
}

export type SessionEventAction =
  | { type: "reset"; sessionId: string; events: readonly SessionEventView[] }
  | { type: "append"; sessionId: string; events: readonly SessionEventView[] };

export function createSessionEventState(sessionId: string): SessionEventState {
  return { sessionId, events: [], highestSeq: -1, missingFromSeq: null };
}

export function sessionEventReducer(
  state: SessionEventState,
  action: SessionEventAction,
): SessionEventState {
  if (action.type === "reset") {
    return buildState(action.sessionId, filteredSortedEvents(action.sessionId, action.events));
  }
  if (action.sessionId !== state.sessionId) return state;
  const nextEvents = filteredSortedEvents(action.sessionId, action.events);
  if (nextEvents.length === 0) return state;
  return appendEvents(state, nextEvents);
}

function appendEvents(
  state: SessionEventState,
  incoming: readonly SessionEventView[],
): SessionEventState {
  const bySeq = new Map(state.events.map((event) => [event.seq, event]));
  let missingFromSeq = state.missingFromSeq;
  for (const event of incoming) {
    if (event.seq > state.highestSeq + 1 && missingFromSeq === null) {
      missingFromSeq = state.highestSeq + 1;
    }
    bySeq.set(event.seq, event);
  }
  const events = [...bySeq.values()].sort((left, right) => left.seq - right.seq);
  return { ...buildState(state.sessionId, events), missingFromSeq };
}

function buildState(sessionId: string, events: SessionEventView[]): SessionEventState {
  return {
    sessionId,
    events,
    highestSeq: events.at(-1)?.seq ?? -1,
    missingFromSeq: null,
  };
}

function filteredSortedEvents(
  sessionId: string,
  events: readonly SessionEventView[],
): SessionEventView[] {
  return events
    .filter((event) => event.session_id === sessionId)
    .sort((left, right) => left.seq - right.seq);
}
