/**
 * Content block rendering.
 *
 * Both request messages and response content arrive as arrays of
 * ContentBlock. We render them with a single component so the
 * visual language stays consistent across request and response.
 */

import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import type { ContentBlock, Message } from "../../types";
import { MasterBar, SECTION_TONE } from "./atoms";

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
      {expanded && (
        <pre className="mt-3 bg-canvas p-4 text-[12px] leading-relaxed text-txt-2 whitespace-pre-wrap border border-edge-subtle block-recess">
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

export const ROLE_TONE: Record<string, { text: string; bg: string }> = {
  user: { text: "text-sky", bg: "bg-sky/5" },
  assistant: { text: "text-sage", bg: "bg-sage/5" },
};

export function RequestMessage({ message }: { message: Message }) {
  const tone = SECTION_TONE[message.role] ?? ROLE_TONE[message.role];
  const { toggleAll, toggleOne, isExpanded } = useCollapsibleSet(message.content.length, true);

  return (
    <div className="card-flush">
      <MasterBar
        label={message.role}
        tone={tone}
        count={message.content.length}
        countUnit="block"
        onToggleAll={toggleAll}
      />
      <div className="hairline-x" />
      <div>
        {message.content.map((block, idx) => (
          <div key={blockKey(block, idx)}>
            <ContentBlockRow
              block={block}
              expanded={isExpanded(idx)}
              onToggleExpanded={() => toggleOne(idx)}
            />
            {idx < message.content.length - 1 && <div className="hairline-x mx-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}
