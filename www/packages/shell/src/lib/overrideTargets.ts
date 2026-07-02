const INDEX_PATTERN = /^(0|-?[1-9][0-9]*)$/;

export interface MessageTarget {
  msgIdx: number;
  blkIdx: number;
}

export function toolTarget(name: string): string {
  return `tool:${name}`;
}

export function systemTarget(index: number): string {
  return `system:${index}`;
}

export function toolResultTarget(toolUseId: string): string {
  return `toolresult:${toolUseId}`;
}

export function samplingTarget(field: string): string {
  return `sampling:${field}`;
}

export function providerExtrasTarget(key: string): string {
  return `provider_extras:${key}`;
}

export function messageBlockTarget(msgIdx: number, blkIdx: number): string {
  return `msg:${msgIdx}:blk:${blkIdx}`;
}

export function parsePrefixed(target: string, prefix: string): string | null {
  return target.startsWith(prefix) ? target.slice(prefix.length) : null;
}

export function parsePrefixedInt(target: string, prefix: string): number | null {
  const raw = parsePrefixed(target, prefix);
  if (raw === null || !INDEX_PATTERN.test(raw)) return null;
  return Number(raw);
}

export function parseToolName(target: string): string | null {
  return parsePrefixed(target, "tool:");
}

export function parseSystemIndex(target: string): number | null {
  return parsePrefixedInt(target, "system:");
}

export function parseToolResultId(target: string): string | null {
  return parsePrefixed(target, "toolresult:");
}

export function parseSamplingField(target: string): string | null {
  return parsePrefixed(target, "sampling:");
}

export function parseProviderExtrasKey(target: string): string | null {
  return parsePrefixed(target, "provider_extras:");
}

export function parseMessageTarget(target: string): MessageTarget | null {
  const parts = target.split(":");
  if (parts.length !== 4 || parts[0] !== "msg" || parts[2] !== "blk") return null;
  const msgIdx = parts[1];
  const blkIdx = parts[3];
  if (msgIdx === undefined || blkIdx === undefined) return null;
  if (!INDEX_PATTERN.test(msgIdx) || !INDEX_PATTERN.test(blkIdx)) return null;
  return { msgIdx: Number(msgIdx), blkIdx: Number(blkIdx) };
}
