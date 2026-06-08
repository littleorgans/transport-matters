export const exchangesPrefix = ["exchanges"] as const;

export function exchangesKey(includeHistory: boolean): readonly ["exchanges", boolean] {
  return ["exchanges", includeHistory];
}

export function exchangeKey(id: string): readonly ["exchange", string] {
  return ["exchange", id];
}

export function turnContentKey(id: string): readonly ["turn-content", string] {
  return ["turn-content", id];
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
  provider?: string | null;
  cli?: string | null;
  status?: string | null;
  limit?: number;
  offset?: number;
  runId?: string | null;
}

export function sessionsKey(args: SessionsKeyArgs) {
  return ["sessions", normalizeSessionArgs(args)] as const;
}

export function launchSessionKey(args: {
  owner: string;
  workspaceHash: string | null;
  cli: string | null;
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
    provider: args.provider ?? null,
    cli: args.cli ?? null,
    status: args.status ?? null,
    limit: args.limit ?? null,
    offset: args.offset ?? null,
    runId: args.runId ?? null,
  } as const;
}
