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
      return `[thinking block, ${block.text.length.toLocaleString()} chars]`;
    case "image":
      return "[image block]";
    case "unknown":
      return "[unknown block]";
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
  const label = blockLabel(block);

  return (
    <div className={`${checked ? "" : "opacity-50"}`}>
      <div className="flex items-start gap-2 px-2 py-1">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="accent-emerald-500 mt-0.5"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-500 font-mono">
              {block.type}
            </span>
            <span className="text-xs text-zinc-600">{blockSize(block).toLocaleString()}</span>
            {block.type === "tool_result" && block.is_error && (
              <span className="rounded bg-red-900/40 px-1 py-0.5 text-xs text-red-400">error</span>
            )}
          </div>
          {canExpand ? (
            <button
              type="button"
              className="text-xs text-zinc-400 mt-0.5 text-left cursor-pointer hover:text-zinc-200 truncate block max-w-full"
              onClick={() => setExpanded((v) => !v)}
            >
              {label}
            </button>
          ) : (
            <span className="text-xs text-zinc-500 mt-0.5 block">{label}</span>
          )}
          {expanded && block.type === "text" && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-zinc-800 p-2 text-xs text-zinc-300 whitespace-pre-wrap font-mono">
              {block.text}
            </pre>
          )}
          {expanded && block.type === "tool_use" && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-zinc-800 p-2 text-xs text-zinc-300 whitespace-pre-wrap font-mono">
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
  const roleBadge =
    message.role === "user" ? "bg-blue-900/40 text-blue-400" : "bg-emerald-900/40 text-emerald-400";

  const keyedBlocks = message.content.map((block, idx) => ({
    block,
    idx,
    key: blockKey(block, idx),
  }));

  return (
    <div className="rounded border border-zinc-800">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900">
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium uppercase ${roleBadge}`}>
          {message.role}
        </span>
        <span className="text-xs text-zinc-500">
          {message.content.length} block{message.content.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="divide-y divide-zinc-800/50">
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
  // Track which blocks are checked per message: map of messageIndex -> Set<blockIndex>
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
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
        Messages ({messages.length})
      </h3>
      <div className="space-y-1">
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
