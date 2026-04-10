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
    <div className={`rounded border ${checked ? "border-zinc-700" : "border-zinc-800 opacity-50"}`}>
      <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="accent-emerald-500"
        />
        <span className="font-mono text-xs text-zinc-500">[{index}]</span>
        <span className="text-xs text-zinc-400">{sizeLabel}</span>
        {part.cache_hint && (
          <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-xs text-amber-400">
            cached
          </span>
        )}
        <span className="ml-auto text-xs text-zinc-600 truncate max-w-60">{preview}</span>
      </div>
      {checked && (
        <button
          type="button"
          className="cursor-pointer px-3 py-1 w-full text-left bg-transparent border-none"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <textarea
              className="w-full min-h-24 max-h-64 resize-y rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200 border border-zinc-700 focus:border-zinc-500 focus:outline-none font-mono"
              value={part.text}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onTextChange(e.target.value)}
            />
          ) : (
            <span className="text-xs text-zinc-500">Click to expand</span>
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
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
        System ({parts.length} parts)
      </h3>
      <div className="space-y-1">
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
