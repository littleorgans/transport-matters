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
  for (const event of incoming) {
    bySeq.set(event.seq, event);
  }
  const events = [...bySeq.values()].sort((left, right) => left.seq - right.seq);
  return buildState(state.sessionId, events);
}

function buildState(sessionId: string, events: SessionEventView[]): SessionEventState {
  return {
    sessionId,
    events,
    highestSeq: events.at(-1)?.seq ?? -1,
    missingFromSeq: findMissingFromSeq(events),
  };
}

function findMissingFromSeq(events: readonly SessionEventView[]): number | null {
  let expectedSeq = 0;
  for (const event of events) {
    if (event.seq > expectedSeq) return expectedSeq;
    if (event.seq === expectedSeq) expectedSeq += 1;
  }
  return null;
}

function filteredSortedEvents(
  _sessionId: string,
  events: readonly SessionEventView[],
): SessionEventView[] {
  return [...events].sort((left, right) => left.seq - right.seq);
}
