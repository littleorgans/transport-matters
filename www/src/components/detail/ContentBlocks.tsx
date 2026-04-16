/**
 * Content block rendering.
 *
 * Response content still goes through the bespoke ``ContentBlockRow``
 * here — responses aren't editable, and the ResponseCard layout stays
 * intentionally quieter than the editor row. Request messages migrated
 * to the editor's ``MessagesSection`` in readOnly mode so the Inspect
 * tab can surface curated text edits as EDIT|DIFF tabs and disabled
 * blocks as greyed-out rows.
 */

import { ColorizedPre } from "../../lib/colorizeLine";
import type { ContentBlock, Message } from "../../types";

// Block type markers are intentionally uniform: a single .chip
// colour across every kind so scanning reads as a quiet index,
// not a traffic light. Semantic colour lives on the row accent
// and in the expanded detail, not on the marker.

/** Total content blocks across all messages. Single source of truth for message counts. */
export function countContentBlocks(messages: Message[]): number {
  return messages.reduce((sum, m) => sum + m.content.length, 0);
}

export function blockSummary(block: ContentBlock, maxPreview = 220): string {
  switch (block.type) {
    case "text": {
      const trimmed = block.text.trim();
      if (trimmed.length === 0) return "(empty)";
      return trimmed.slice(0, maxPreview) + (trimmed.length > maxPreview ? "\u2026" : "");
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

export function ContentBlockRow({
  block,
  expanded,
  onToggleExpanded,
}: {
  block: ContentBlock;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const isError = block.type === "tool_result" && block.is_error;

  return (
    <div className="px-4 py-2.5">
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex w-full cursor-pointer items-start gap-3 text-left"
      >
        <span className="chip shrink-0">{block.type}</span>
        {isError && <span className="chip shrink-0 text-rose">error</span>}
        <span className="text-[13px] text-txt-2 truncate leading-5 mt-0.5 flex-1 min-w-0">
          {blockSummary(block)}
        </span>
      </button>
      {expanded &&
        (block.type === "text" || block.type === "thinking" ? (
          <pre className="mt-3 bg-canvas p-4 text-[12px] leading-relaxed text-txt-2 whitespace-pre-wrap border border-edge-subtle block-recess">
            {block.text}
          </pre>
        ) : (
          <ColorizedPre
            text={JSON.stringify(block, null, 2)}
            className="mt-3 bg-canvas p-4 text-[12px] leading-relaxed text-txt-2 whitespace-pre-wrap border border-edge-subtle block-recess"
          />
        ))}
    </div>
  );
}

// ── Role tone ──────────────────────────────────────────────────────
// Tint palette shared with the editor's MessageCard so user and
// assistant rows read the same in the Breakpoint editor and in the
// readOnly Inspect tab.

export const ROLE_TONE: Record<string, { text: string; bg: string }> = {
  user: { text: "text-sky", bg: "bg-sky/5" },
  assistant: { text: "text-sage", bg: "bg-sage/5" },
};
