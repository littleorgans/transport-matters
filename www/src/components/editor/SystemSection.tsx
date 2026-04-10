import { useState } from "react";
import type { SystemPart } from "../../types";
import { Toggle } from "../Toggle";

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
    <div className={`card-flush transition-opacity ${checked ? "" : "opacity-40"}`}>
      <div className="flex items-center gap-3 px-4 py-2.5">
        <Toggle checked={checked} onChange={() => onToggle()} label={`Toggle part ${index}`} />
        <span className="chip metric-num">{`[${index}]`}</span>
        <span className="label text-txt-3 metric-num">{sizeLabel}</span>
        {part.cache_hint && <span className="chip text-amber">cached</span>}
        <span className="ml-auto text-[11px] text-txt-3 truncate max-w-60">{preview}</span>
      </div>
      {checked && (
        <>
          <div className="hairline-x" />
          <button
            type="button"
            className="cursor-pointer px-4 py-3 w-full text-left bg-transparent border-none"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <textarea
                className="w-full min-h-24 max-h-64 resize-y bg-canvas px-3 py-2 text-[11px] text-txt border border-edge focus:border-sky/50 focus:outline-none transition-colors"
                value={part.text}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => onTextChange(e.target.value)}
              />
            ) : (
              <span className="label">Click to expand</span>
            )}
          </button>
        </>
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
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">System &middot; {parts.length} parts</span>
      </div>
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
    </section>
  );
}
