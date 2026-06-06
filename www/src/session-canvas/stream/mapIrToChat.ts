import type { ContentBlock, ImageBlock, UnknownBlock } from "../../types";
import type { SessionEventView } from "../api/sessionEvents";

export interface TranscriptMessageModel {
  id: string;
  seq: number;
  role: string;
  kind: "turn" | "meta" | "unknown";
  blocks: ContentBlock[];
  timestamp: string | null;
  sourcePath: string | null;
  sourceLine: number | null;
}

export type ChatItem = TranscriptMessageModel;

export function mapSessionEventToChatItems(event: SessionEventView): ChatItem[] {
  const message = mapSessionEventToTranscriptMessage(event);
  return message ? [message] : [];
}

function mapSessionEventToTranscriptMessage(
  event: SessionEventView,
): TranscriptMessageModel | null {
  if (event.kind === "meta") return mapMetaEvent(event);
  if (event.kind !== "turn") return mapUnknownEvent(event);
  if (!event.ir) return mapUnknownEvent(event);
  const parts = event.ir.parts;
  if (!Array.isArray(parts)) return mapUnknownEvent(event);
  const blocks = parts.map(normalizeContentBlock);
  return buildMessage(event, "turn", blocks.length > 0 ? blocks : fallbackBlocks(event));
}

function mapMetaEvent(event: SessionEventView): TranscriptMessageModel {
  return buildMessage(event, "meta", [metadataBlock(event)]);
}

function mapUnknownEvent(event: SessionEventView): TranscriptMessageModel {
  return buildMessage(event, "unknown", [metadataBlock(event)]);
}

function buildMessage(
  event: SessionEventView,
  kind: TranscriptMessageModel["kind"],
  blocks: ContentBlock[],
): TranscriptMessageModel {
  return {
    id: `${event.session_id}:${event.seq}`,
    seq: event.seq,
    role: kind === "meta" ? "metadata" : (event.role ?? "unknown"),
    kind,
    blocks,
    timestamp: event.ts ?? event.created_at,
    sourcePath: event.source_path,
    sourceLine: event.source_line,
  };
}

function fallbackBlocks(event: SessionEventView): ContentBlock[] {
  if (event.search_text) return [textBlock(event.search_text)];
  return [metadataBlock(event)];
}

function metadataBlock(event: SessionEventView): ContentBlock {
  return textBlock(
    [
      `kind: ${event.kind}`,
      `seq: ${event.seq}`,
      `native_turn_id: ${event.native_turn_id ?? "none"}`,
      `ts: ${event.ts ?? event.created_at ?? "none"}`,
      `model: ${event.model ?? "none"}`,
      `source_path: ${event.source_path ?? "none"}`,
      `source_line: ${event.source_line ?? "none"}`,
    ].join("\n"),
  );
}

function textBlock(text: string): ContentBlock {
  return { type: "text", text, provider_data: null };
}

function normalizeContentBlock(value: unknown): ContentBlock {
  if (!isRecord(value)) return unknownBlock("non_object", value);
  if (value.type === "text" && typeof value.text === "string") {
    return { type: "text", text: value.text, provider_data: providerData(value) };
  }
  if (value.type === "thinking" && typeof value.text === "string") {
    return { type: "thinking", text: value.text, provider_data: providerData(value) };
  }
  if (value.type === "tool_use" && typeof value.id === "string" && typeof value.name === "string") {
    return {
      type: "tool_use",
      id: value.id,
      name: value.name,
      input: isRecord(value.input) ? value.input : {},
      provider_data: providerData(value),
    };
  }
  if (value.type === "tool_result" && typeof value.tool_use_id === "string") {
    const content = Array.isArray(value.content) ? value.content.map(normalizeToolResultBlock) : [];
    return {
      type: "tool_result",
      tool_use_id: value.tool_use_id,
      content,
      is_error: value.is_error === true,
      provider_data: providerData(value),
    };
  }
  if (value.type === "image") return normalizeImageBlock(value);
  return unknownBlock(String(value.type ?? "unknown"), value);
}

function normalizeToolResultBlock(
  value: unknown,
): ContentBlock extends infer T ? Extract<T, { type: "text" | "image" | "unknown" }> : never {
  const block = normalizeContentBlock(value);
  if (block.type === "tool_use" || block.type === "thinking" || block.type === "tool_result") {
    return unknownBlock(block.type, block) as never;
  }
  return block as never;
}

function normalizeImageBlock(value: Record<string, unknown>): ImageBlock {
  if (isRecord(value.source)) {
    return { type: "image", source: value.source, provider_data: providerData(value) };
  }
  if (typeof value.artifact_hash === "string") {
    return {
      type: "image",
      source: {
        artifact_hash: value.artifact_hash,
        media_type: typeof value.media_type === "string" ? value.media_type : null,
        redacted: true,
      },
      provider_data: providerData(value),
    };
  }
  return { type: "image", source: {}, provider_data: providerData(value) };
}

function unknownBlock(kind: string, payload: unknown): UnknownBlock {
  return {
    type: "unknown",
    raw: {
      raw_type: kind,
      value: isRecord(payload) ? payload : { value: payload },
    },
  };
}

function providerData(value: Record<string, unknown>): Record<string, unknown> | null {
  return isRecord(value.provider_data) ? value.provider_data : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
