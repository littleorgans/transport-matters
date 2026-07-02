export const exchangesPrefix = ["exchanges"] as const;

export function exchangesKey(runId: string | null): readonly ["exchanges", string | null] {
  return ["exchanges", runId];
}

export function exchangeKey(
  runId: string | null,
  id: string,
): readonly ["exchange", string | null, string] {
  return ["exchange", runId, id];
}

export function turnContentKey(
  runId: string | null,
  id: string,
): readonly ["turn-content", string | null, string] {
  return ["turn-content", runId, id];
}

export function resourceContentKey(args: {
  sessionId: string;
  resourceId: string;
  owner: string;
  rangeStart?: number | null;
  rangeEnd?: number | null;
  includeDebug?: boolean;
}) {
  return [
    "session-resource",
    {
      sessionId: args.sessionId,
      resourceId: args.resourceId,
      owner: args.owner,
      rangeStart: args.rangeStart ?? null,
      rangeEnd: args.rangeEnd ?? null,
      includeDebug: args.includeDebug ?? false,
    },
  ] as const;
}

export interface SessionsKeyArgs {
  owner: string;
  workspaceHash?: string | null;
  harness?: string | null;
  purpose?: string | null;
  visibility?: string | null;
  includeInternal?: boolean | null;
  limit?: number;
  cursor?: string | null;
  runId?: string | null;
}

export function sessionsKey(args: SessionsKeyArgs) {
  return ["sessions", normalizeSessionArgs(args)] as const;
}

export function launchSessionKey(args: {
  owner: string;
  workspaceHash: string | null;
  harness: string | null;
  runId: string | null;
}) {
  return ["session-launch", normalizeSessionArgs(args)] as const;
}

export function sessionEventsKey(args: {
  sessionId: string;
  owner: string;
  fromSeq?: number | null;
  toSeq?: number | null;
  limit?: number;
}) {
  return [
    "session-events",
    {
      sessionId: args.sessionId,
      owner: args.owner,
      fromSeq: args.fromSeq ?? null,
      toSeq: args.toSeq ?? null,
      limit: args.limit ?? null,
    },
  ] as const;
}

function normalizeSessionArgs(args: SessionsKeyArgs) {
  return {
    owner: args.owner,
    workspaceHash: args.workspaceHash ?? null,
    harness: args.harness ?? null,
    purpose: args.purpose ?? null,
    visibility: args.visibility ?? null,
    includeInternal: args.includeInternal ?? null,
    limit: args.limit ?? null,
    cursor: args.cursor ?? null,
    runId: args.runId ?? null,
  } as const;
}
