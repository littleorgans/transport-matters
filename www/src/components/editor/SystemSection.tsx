import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import { useEditableOverride } from "../../hooks/useEditableOverride";
import { useUIStore } from "../../stores/uiStore";
import type { Override, SystemPart } from "../../types";
import { inputClass, MasterBar, OriginalPreview, SECTION_TONE } from "../detail/atoms";
import { Toggle } from "../Toggle";

interface SystemSectionProps {
  parts: SystemPart[];
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

function SystemPartRow({
  part,
  index,
  overrides,
  onOverride,
  expanded,
  onToggleExpanded,
}: {
  part: SystemPart;
  index: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const target = `system:${index}`;
  const {
    checked,
    isModified,
    localText,
    setLocalText,
    textRef,
    handleToggle,
    commitText,
    handleReset,
  } = useEditableOverride({
    originalValue: part.text,
    overrides,
    onOverride,
    toggleKind: "system_part_toggle",
    textKind: "system_part_text",
    target,
    initialExpanded: true,
  });

  const sizeLabel = `${part.text.length.toLocaleString()} chars`;

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      {/* Row header — click-to-expand strip. Toggle and Reset are
          stopPropagation islands so they never fold the row. */}
      {/* biome-ignore lint/a11y/useSemanticElements: composite row wraps a Toggle button and a Reset button; button-in-button is invalid HTML */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggleExpanded();
          }
        }}
        className="flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors hover:bg-raised focus:outline-none focus-visible:bg-raised"
      >
        {/* biome-ignore lint/a11y/useKeyWithClickEvents: stopPropagation wrapper, the inner Toggle handles its own keyboard events */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: click-swallow wrapper isolates the Toggle from the row's expand handler */}
        <div onClick={(e) => e.stopPropagation()}>
          <Toggle checked={checked} onChange={handleToggle} label={`Toggle part ${index}`} />
        </div>
        <span className="chip metric-num">{`[${index}]`}</span>
        <span className="label text-txt-3 metric-num">{sizeLabel}</span>
        {part.cache_hint && <span className="chip text-amber">cached</span>}
        {isModified && <span className="h-1 w-1 rounded-full bg-amber" />}
        {isModified && (
          <button
            type="button"
            className="label shrink-0 cursor-pointer text-txt-3 transition-colors hover:text-amber"
            onClick={(e) => {
              e.stopPropagation();
              handleReset();
            }}
          >
            reset
          </button>
        )}
        <div className="flex-1" />
      </div>
      {expanded && (
        <div className="mt-2 space-y-2 px-4 pb-3">
          <textarea
            ref={textRef}
            className={inputClass}
            value={localText}
            onChange={(e) => setLocalText(e.target.value)}
            onBlur={commitText}
          />
          {isModified && <OriginalPreview text={part.text} />}
        </div>
      )}
    </div>
  );
}

export function SystemSection({ parts, overrides, onOverride }: SystemSectionProps) {
  const overrideCount = overrides.filter(
    (o) => o.kind === "system_part_toggle" || o.kind === "system_part_text",
  ).length;

  const keyedParts = parts.map((part, idx) => ({
    part,
    idx,
    key: `system-${idx}-${part.text.slice(0, 20)}`,
  }));

  // Seeded from the auto-expand pref in the initializer only, so
  // mid-session flips don't retroactively collapse mounted rows.
  const autoExpandBlocks = useUIStore((s) => s.autoExpandBlocks);
  const { toggleAll, toggleOne, isExpanded } = useCollapsibleSet(parts.length, !autoExpandBlocks);

  // Nothing to show and nothing to edit when the request carries no
  // system parts. Mirrors the early return in ToolsSection and the
  // conditional render the detail view uses in InspectTab, so empty
  // system payloads don't leave a "0 parts" master bar hanging. Placed
  // after hooks to respect React's rules-of-hooks ordering.
  if (parts.length === 0) return null;

  return (
    <section className="space-y-4">
      <div className="card-flush">
        <MasterBar
          label="system"
          tone={SECTION_TONE.system}
          count={parts.length}
          countUnit="part"
          extras={
            overrideCount > 0 ? (
              <>
                <span className="h-1 w-1 rounded-full bg-amber" />
                <span className="label text-amber">
                  {overrideCount} override{overrideCount !== 1 ? "s" : ""}
                </span>
              </>
            ) : undefined
          }
          onToggleAll={toggleAll}
        />
        <div className="hairline-x" />
        <div>
          {keyedParts.map((entry, i) => (
            <div key={entry.key}>
              <SystemPartRow
                part={entry.part}
                index={entry.idx}
                overrides={overrides}
                onOverride={onOverride}
                expanded={isExpanded(entry.idx)}
                onToggleExpanded={() => toggleOne(entry.idx)}
              />
              {i < keyedParts.length - 1 && <div className="hairline-x mx-4" />}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
