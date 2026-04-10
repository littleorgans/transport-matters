import { useState } from "react";
import type { ContentBlock, Message } from "../../types";

interface MessagesSectionProps {
  messages: Message[];
  onChange: (messages: Message[]) => void;
}

function blockLabel(block: ContentBlock): string {
  switch (block.type) {
    case "text":
      return block.text.slice(0, 120) + (block.text.length > 120 ? "..." : "");
    case "tool_use":
      return `tool_use: ${block.name} (${block.id.slice(0, 12)})`;
    case "tool_result":
      return `tool_result: ${block.tool_use_id.slice(0, 12)}${block.is_error ? " [error]" : ""}`;
    case "thinking":
      return `[thinking, ${block.text.length.toLocaleString()} chars]`;
    case "image":
      return "[image]";
    case "unknown":
      return "[unknown]";
  }
}

function blockSize(block: ContentBlock): number {
  return JSON.stringify(block).length;
}

function BlockRow({
  block,
  checked,
  onToggle,
}: {
  block: ContentBlock;
  checked: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = block.type === "text" || block.type === "tool_use";

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      <div className="flex items-start gap-2.5 px-3 py-2">
        <input type="checkbox" checked={checked} onChange={onToggle} className="mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-raised px-1.5 py-0.5 text-[9px] uppercase text-txt-3">
              {block.type}
            </span>
            <span className="text-[10px] text-txt-3 tabular-nums">
              {blockSize(block).toLocaleString()}
            </span>
            {block.type === "tool_result" && block.is_error && (
              <span className="rounded bg-rose/10 px-1.5 py-0.5 text-[10px] text-rose">error</span>
            )}
          </div>
          {canExpand ? (
            <button
              type="button"
              className="text-[11px] text-txt-2 mt-1 text-left cursor-pointer hover:text-txt truncate block max-w-full transition-colors"
              onClick={() => setExpanded((v) => !v)}
            >
              {blockLabel(block)}
            </button>
          ) : (
            <span className="text-[11px] text-txt-3 mt-1 block">{blockLabel(block)}</span>
          )}
          {expanded && block.type === "text" && (
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-canvas p-3 text-[10px] text-txt-2 whitespace-pre-wrap">
              {block.text}
            </pre>
          )}
          {expanded && block.type === "tool_use" && (
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-canvas p-3 text-[10px] text-txt-2 whitespace-pre-wrap">
              {JSON.stringify(block.input, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function blockKey(block: ContentBlock, index: number): string {
  switch (block.type) {
    case "tool_use":
      return block.id;
    case "tool_result":
      return `result-${block.tool_use_id}`;
    default:
      return `${block.type}-${index}`;
  }
}

function MessageCard({
  message,
  checkedBlocks,
  onToggleBlock,
}: {
  message: Message;
  checkedBlocks: Set<number>;
  onToggleBlock: (blockIndex: number) => void;
}) {
  const roleBadge = message.role === "user" ? "text-sky bg-sky/8" : "text-sage bg-sage/8";

  const keyedBlocks = message.content.map((block, idx) => ({
    block,
    idx,
    key: blockKey(block, idx),
  }));

  return (
    <div className="rounded-md border border-edge overflow-hidden">
      <div className="flex items-center gap-2.5 px-4 py-2.5 bg-surface">
        <span className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase ${roleBadge}`}>
          {message.role}
        </span>
        <span className="text-[10px] text-txt-3">
          {message.content.length} block{message.content.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="divide-y divide-edge-subtle">
        {keyedBlocks.map((entry) => (
          <BlockRow
            key={entry.key}
            block={entry.block}
            checked={checkedBlocks.has(entry.idx)}
            onToggle={() => onToggleBlock(entry.idx)}
          />
        ))}
      </div>
    </div>
  );
}

export function MessagesSection({ messages, onChange }: MessagesSectionProps) {
  const [checkedMap, setCheckedMap] = useState<Map<number, Set<number>>>(() => {
    const map = new Map<number, Set<number>>();
    messages.forEach((msg, mi) => {
      map.set(mi, new Set(msg.content.map((_, bi) => bi)));
    });
    return map;
  });

  const emitChange = (nextMap: Map<number, Set<number>>) => {
    const result: Message[] = messages.map((msg, mi) => {
      const checked = nextMap.get(mi) ?? new Set<number>();
      const filteredContent = msg.content.filter((_, bi) => checked.has(bi));
      return { ...msg, content: filteredContent };
    });
    onChange(result);
  };

  const toggleBlock = (messageIndex: number, blockIndex: number) => {
    setCheckedMap((prev) => {
      const next = new Map(prev);
      const blockSet = new Set(next.get(messageIndex) ?? new Set<number>());
      if (blockSet.has(blockIndex)) {
        blockSet.delete(blockIndex);
      } else {
        blockSet.add(blockIndex);
      }
      next.set(messageIndex, blockSet);
      emitChange(next);
      return next;
    });
  };

  const keyedMessages = messages.map((msg, idx) => ({
    msg,
    idx,
    key: `${msg.role}-${idx}`,
  }));

  return (
    <div className="space-y-3">
      <h3 className="text-[10px] font-medium text-txt-3 uppercase tracking-[0.12em]">
        Messages ({messages.length})
      </h3>
      <div className="space-y-2">
        {keyedMessages.map((entry) => (
          <MessageCard
            key={entry.key}
            message={entry.msg}
            checkedBlocks={checkedMap.get(entry.idx) ?? new Set<number>()}
            onToggleBlock={(bi) => toggleBlock(entry.idx, bi)}
          />
        ))}
      </div>
    </div>
  );
}
