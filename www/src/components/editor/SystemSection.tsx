import { useState } from "react";
import type { SystemPart } from "../../types";

interface SystemSectionProps {
  parts: SystemPart[];
  onChange: (parts: SystemPart[]) => void;
}

function SystemCard({
  part,
  index,
  checked,
  onToggle,
  onTextChange,
}: {
  part: SystemPart;
  index: number;
  checked: boolean;
  onToggle: () => void;
  onTextChange: (text: string) => void;
}) {
  const [expanded, setExpanded] = useState(part.text.length <= 500);

  const preview = part.text.slice(0, 60) + (part.text.length > 60 ? "..." : "");
  const sizeLabel = `${part.text.length.toLocaleString()} chars`;

  return (
    <div
      className={`rounded-md border transition-opacity ${
        checked ? "border-edge" : "border-edge-subtle opacity-40"
      }`}
    >
      <div className="flex items-center gap-2.5 px-4 py-2.5 bg-surface">
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span className="text-[10px] text-txt-3 tabular-nums">[{index}]</span>
        <span className="text-[10px] text-txt-3 tabular-nums">{sizeLabel}</span>
        {part.cache_hint && (
          <span className="rounded bg-amber/10 px-1.5 py-0.5 text-[10px] text-amber">cached</span>
        )}
        <span className="ml-auto text-[10px] text-txt-3 truncate max-w-60">{preview}</span>
      </div>
      {checked && (
        <button
          type="button"
          className="cursor-pointer px-4 py-2 w-full text-left bg-transparent border-none"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <textarea
              className="w-full min-h-24 max-h-64 resize-y rounded-md bg-canvas px-3 py-2 text-[11px] text-txt border border-edge focus:border-sky/40 focus:outline-none transition-colors"
              value={part.text}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onTextChange(e.target.value)}
            />
          ) : (
            <span className="text-[10px] text-txt-3">Click to expand</span>
          )}
        </button>
      )}
    </div>
  );
}

export function SystemSection({ parts, onChange }: SystemSectionProps) {
  const [checkedSet, setCheckedSet] = useState<Set<number>>(() => new Set(parts.map((_, i) => i)));

  const handleToggle = (index: number) => {
    setCheckedSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      const kept = parts.filter((_, i) => next.has(i));
      onChange(kept);
      return next;
    });
  };

  const handleTextChange = (index: number, text: string) => {
    const updated = parts.map((p, i) => (i === index ? { ...p, text } : p));
    onChange(updated.filter((_, i) => checkedSet.has(i)));
  };

  const keyedParts = parts.map((part, idx) => ({
    part,
    idx,
    key: `system-${idx}-${part.text.slice(0, 20)}`,
  }));

  return (
    <div className="space-y-3">
      <h3 className="text-[10px] font-medium text-txt-3 uppercase tracking-[0.12em]">
        System ({parts.length} parts)
      </h3>
      <div className="space-y-2">
        {keyedParts.map((entry) => (
          <SystemCard
            key={entry.key}
            part={entry.part}
            index={entry.idx}
            checked={checkedSet.has(entry.idx)}
            onToggle={() => handleToggle(entry.idx)}
            onTextChange={(text) => handleTextChange(entry.idx, text)}
          />
        ))}
      </div>
    </div>
  );
}
