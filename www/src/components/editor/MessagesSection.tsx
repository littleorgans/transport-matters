import { useEffect, useState } from "react";
import type { ContentBlock, Message } from "../../types";
import { Toggle } from "../Toggle";

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
      <div className="flex items-start gap-3 px-4 py-2.5">
        <div className="mt-0.5">
          <Toggle
            checked={checked}
            onChange={() => onToggle()}
            label={`Toggle ${block.type} block`}
          />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <span className="chip">{block.type}</span>
            <span className="label text-txt-3 metric-num">{blockSize(block).toLocaleString()}</span>
            {block.type === "tool_result" && block.is_error && (
              <span className="chip text-rose">error</span>
            )}
          </div>
          {canExpand ? (
            <button
              type="button"
              className="text-[11px] text-txt-2 mt-1.5 text-left cursor-pointer hover:text-txt truncate block max-w-full transition-colors"
              onClick={() => setExpanded((v) => !v)}
            >
              {blockLabel(block)}
            </button>
          ) : (
            <span className="text-[11px] text-txt-3 mt-1.5 block">{blockLabel(block)}</span>
          )}
          {expanded && block.type === "text" && (
            <pre className="mt-2 max-h-48 overflow-auto bg-canvas p-3 text-[10px] text-txt-2 whitespace-pre-wrap border border-edge-subtle">
              {block.text}
            </pre>
          )}
          {expanded && block.type === "tool_use" && (
            <pre className="mt-2 max-h-48 overflow-auto bg-canvas p-3 text-[10px] text-txt-2 whitespace-pre-wrap border border-edge-subtle">
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
  const roleTone =
    message.role === "user"
      ? { text: "text-sky", bg: "bg-sky/5" }
      : { text: "text-sage", bg: "bg-sage/5" };

  const keyedBlocks = message.content.map((block, idx) => ({
    block,
    idx,
    key: blockKey(block, idx),
  }));

  return (
    <div className="card-flush">
      <div className={`flex items-center gap-3 px-4 py-2.5 ${roleTone.bg}`}>
        <span className={`chip ${roleTone.text}`}>{message.role}</span>
        <span className="text-[11px] text-txt-3 metric-num">
          {message.content.length} block{message.content.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="hairline-x" />
      <div>
        {keyedBlocks.map((entry, i) => (
          <div key={entry.key}>
            <BlockRow
              block={entry.block}
              checked={checkedBlocks.has(entry.idx)}
              onToggle={() => onToggleBlock(entry.idx)}
            />
            {i < keyedBlocks.length - 1 && <div className="hairline-x mx-4" />}
          </div>
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

  // Reseed when the messages prop changes (e.g. a second paused flow with
  // different content arrives without the component unmounting).
  useEffect(() => {
    const map = new Map<number, Set<number>>();
    messages.forEach((msg, mi) => {
      map.set(mi, new Set(msg.content.map((_, bi) => bi)));
    });
    setCheckedMap(map);
  }, [messages]);

  const emitChange = (nextMap: Map<number, Set<number>>) => {
    const result: Message[] = messages.map((msg, mi) => {
      const checked = nextMap.get(mi) ?? new Set<number>();
      const filteredContent = msg.content.filter((_, bi) => checked.has(bi));
      return { ...msg, content: filteredContent };
    });
    onChange(result);
  };

  const toggleBlock = (messageIndex: number, blockIndex: number) => {
    const next = new Map(checkedMap);
    const blockSet = new Set(next.get(messageIndex) ?? new Set<number>());
    if (blockSet.has(blockIndex)) {
      blockSet.delete(blockIndex);
    } else {
      blockSet.add(blockIndex);
    }
    next.set(messageIndex, blockSet);
    setCheckedMap(next);
    emitChange(next);
  };

  const keyedMessages = messages.map((msg, idx) => ({
    msg,
    idx,
    key: `${msg.role}-${idx}`,
  }));

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Messages &middot; {messages.length}</span>
      </div>
      <div className="space-y-3">
        {keyedMessages.map((entry) => (
          <MessageCard
            key={entry.key}
            message={entry.msg}
            checkedBlocks={checkedMap.get(entry.idx) ?? new Set<number>()}
            onToggleBlock={(bi) => toggleBlock(entry.idx, bi)}
          />
        ))}
      </div>
    </section>
  );
}
