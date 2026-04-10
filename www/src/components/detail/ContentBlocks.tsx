/**
 * Content block rendering.
 *
 * Both request messages and response content arrive as arrays of
 * ContentBlock. We render them with a single component so the
 * visual language stays consistent across request and response.
 */

import { useState } from "react";
import type { ContentBlock, Message } from "../../types";

// Block type markers are intentionally uniform: a single .chip
// colour across every kind so scanning reads as a quiet index,
// not a traffic light. Semantic colour lives on the row accent
// and in the expanded detail, not on the marker.

function blockSummary(block: ContentBlock): string {
  switch (block.type) {
    case "text": {
      const trimmed = block.text.trim();
      if (trimmed.length === 0) return "(empty)";
      return trimmed.slice(0, 220) + (trimmed.length > 220 ? "\u2026" : "");
    }
    case "tool_use":
      return `${block.name}  \u00b7  ${block.id.slice(0, 8)}`;
    case "tool_result":
      return `\u2192 ${block.tool_use_id.slice(0, 8)}${block.is_error ? "  [error]" : ""}`;
    case "thinking":
      return `${block.text.length.toLocaleString()} chars of reasoning`;
    case "image":
      return "image";
    case "unknown":
      return "unknown block";
  }
}

export function blockKey(block: ContentBlock, idx: number): string {
  switch (block.type) {
    case "tool_use":
      return `tu-${block.id}`;
    case "tool_result":
      return `tr-${block.tool_use_id}`;
    default:
      return `${block.type}-${idx}`;
  }
}

// ── Content block ──────────────────────────────────────────────────
// Click to expand. Summary on the closed state, pre-formatted
// detail on the open state.

export function ContentBlockRow({ block }: { block: ContentBlock }) {
  const [expanded, setExpanded] = useState(false);
  const isError = block.type === "tool_result" && block.is_error;

  return (
    <div className="px-4 py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-start gap-3 text-left"
      >
        <span className="chip shrink-0">{block.type}</span>
        {isError && <span className="chip shrink-0 text-rose">error</span>}
        <span className="text-[11px] text-txt-2 truncate leading-5 mt-0.5">
          {blockSummary(block)}
        </span>
      </button>
      {expanded && (
        <pre
          className="mt-3 max-h-72 overflow-auto bg-canvas p-4 text-[10px] leading-relaxed text-txt-2 whitespace-pre-wrap border border-edge-subtle"
          style={{ boxShadow: "inset 0 1px 0 0 rgba(0,0,0,0.4)" }}
        >
          {block.type === "text" || block.type === "thinking"
            ? block.text
            : JSON.stringify(block, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Request message ────────────────────────────────────────────────
// Wraps a role chip + block list. The role colour tints the chip
// text and the header's faint background wash. Block rows stay
// uniform so scanning reads as a quiet index.

const ROLE_TONE: Record<string, { text: string; bg: string }> = {
  user: { text: "text-sky", bg: "bg-sky/5" },
  assistant: { text: "text-sage", bg: "bg-sage/5" },
};

export function RequestMessage({ message }: { message: Message }) {
  const tone = ROLE_TONE[message.role] ?? { text: "text-txt-2", bg: "bg-raised" };

  return (
    <div className="card-flush">
      <div className={`flex items-center gap-3 px-4 py-2.5 ${tone.bg}`}>
        <span className={`chip ${tone.text}`}>{message.role}</span>
        <span className="ml-auto text-[11px] text-txt-3 metric-num">
          {message.content.length} block{message.content.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="hairline-x" />
      <div>
        {message.content.map((block, idx) => (
          <div key={blockKey(block, idx)}>
            <ContentBlockRow block={block} />
            {idx < message.content.length - 1 && <div className="hairline-x mx-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}
